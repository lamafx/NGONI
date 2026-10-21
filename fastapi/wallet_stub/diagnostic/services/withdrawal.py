"""Logique de resolution du diagnostic de retrait -- PORTE MANUELLE de
DiagnosticController::withdrawal() (ngoni-wallet-service). Toute evolution du
controller PHP (nouvelle cause, nouveau seuil SLA...) doit etre repercutee
ici si on veut continuer a tester ce cas localement (voir README.md)."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ...db import Wallet, WalletTransaction
from ...outcomes import escalate, resolved
from ..formatting import format_datetime, format_duration_minutes
from .lookup_helpers import parse_amount, parse_relative_date_fr

# Doit rester identique a DiagnosticController::WITHDRAWAL_PENDING_SLA_MINUTES.
WITHDRAWAL_PENDING_SLA_MINUTES = 120


def resolve_withdrawal(
    db: Session,
    user_id_raw: str,
    reference: str | None,
    incident_date: str | None = None,
    amount: str | None = None,
) -> dict:
    try:
        user_id = uuid.UUID(user_id_raw)
    except ValueError:
        return escalate(
            "Identifiant utilisateur invalide.",
            "WALLET_NOT_FOUND",
            "Wallet",
            "high",
            {"user_id": user_id_raw, "transaction_reference": reference},
        )

    wallet = db.query(Wallet).filter_by(user_id=user_id).first()
    if wallet is None:
        return escalate(
            "Je ne retrouve pas de portefeuille associé à votre compte. Je transmets cela à notre équipe technique.",
            "WALLET_NOT_FOUND",
            "Wallet",
            "high",
            {"user_id": user_id_raw, "transaction_reference": reference},
        )

    if reference:
        tx = (
            db.query(WalletTransaction)
            .filter_by(wallet_id=wallet.id, type="WITHDRAWAL", reference_id=reference)
            .first()
        )
        if tx is None:
            return _resolve_missing_transaction(wallet, reference, user_id_raw)
        return _resolve_existing_transaction(wallet, tx, reference)

    # Repli sans reference (rapport utilisateur, "champs alternatifs") :
    # l'utilisateur a indique ne pas avoir sa reference de transaction (voir
    # intent cannot_provide_field, rasa/actions/diagnostic.py) -- recherche
    # par date + montant du retrait plutot que par identifiant exact.
    return _resolve_by_date_amount(db, wallet, user_id_raw, incident_date, amount)


def _resolve_by_date_amount(
    db: Session, wallet: Wallet, user_id_raw: str, incident_date: str | None, amount: str | None
) -> dict:
    parsed_date = parse_relative_date_fr(incident_date, datetime.now(timezone.utc))
    parsed_amount = parse_amount(amount)
    if parsed_date is None or parsed_amount is None:
        # Expression non reconnue (pattern borne, voir lookup_helpers.py) :
        # pas d'approximation risquee, on redemande la reference plutot que
        # de chercher sur une interpretation incertaine.
        return escalate(
            "Je n'ai pas réussi à identifier précisément ce retrait à partir de la date et du montant "
            "indiqués. Je transmets votre demande à notre équipe technique.",
            "AMBIGUOUS_DATE_OR_AMOUNT",
            "Wallet",
            "medium",
            {"user_id": user_id_raw, "incident_date": incident_date, "amount": amount},
        )

    day_start = datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    matches = (
        db.query(WalletTransaction)
        .filter(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.type == "WITHDRAWAL",
            WalletTransaction.created_at >= day_start,
            WalletTransaction.created_at < day_end,
            WalletTransaction.amount == parsed_amount,
        )
        .all()
    )

    if not matches:
        return _resolve_missing_transaction(
            wallet,
            None,
            user_id_raw,
            locator_label="cette date et ce montant",
            extra_context={"incident_date": incident_date, "amount": amount},
        )

    if len(matches) > 1:
        return escalate(
            "Plusieurs retraits correspondent à cette date et ce montant. Pourriez-vous préciser la "
            "référence de la transaction pour lever l'ambiguïté ?",
            "MULTIPLE_TRANSACTIONS_MATCH",
            "Wallet",
            "medium",
            {
                "user_id": user_id_raw,
                "incident_date": incident_date,
                "amount": amount,
                "count": len(matches),
            },
        )

    tx = matches[0]
    return _resolve_existing_transaction(wallet, tx, tx.reference_id)


def _account_frozen_outcome(wallet: Wallet, reference: str, user_id_raw: str, *, still_pending: bool) -> dict:
    since = format_datetime(wallet.frozen_at)
    since_suffix = f" depuis le {since}" if since else ""
    reason_suffix = f" Raison indiquée : {wallet.frozen_reason}." if wallet.frozen_reason else ""
    cause = "reste bloqué en attente" if still_pending else "n'a jamais pu être initié"
    return escalate(
        f"Votre portefeuille est actuellement gelé (statut : {wallet.status}){since_suffix}.{reason_suffix} "
        f"C'est probablement pour cette raison que ce retrait {cause}. Je transmets cela à notre "
        "équipe technique pour réexamen.",
        "ACCOUNT_FROZEN",
        "Wallet",
        "high",
        {
            "user_id": user_id_raw,
            "transaction_reference": reference,
            "status": wallet.status,
            "frozen_reason": wallet.frozen_reason,
            "frozen_at": wallet.frozen_at.isoformat() if wallet.frozen_at else None,
        },
    )


def _frozen_note(wallet: Wallet) -> str:
    # Complement informatif (pas une cause presumee) quand la transaction a
    # deja un statut definitif ou en cours propre a elle -- voir
    # _resolve_existing_transaction.
    if wallet.status == "ACTIVE":
        return ""
    since = format_datetime(wallet.frozen_at)
    since_suffix = f" depuis le {since}" if since else ""
    note = f" Notez par ailleurs que votre portefeuille est actuellement gelé (statut : {wallet.status}){since_suffix}"
    if wallet.frozen_reason:
        note += f", raison indiquée : {wallet.frozen_reason}"
    return note + "."


def _resolve_missing_transaction(
    wallet: Wallet,
    reference: str | None,
    user_id_raw: str,
    *,
    locator_label: str = "cette référence",
    extra_context: dict | None = None,
) -> dict:
    # Aucune transaction du tout (par reference, ou par date+montant en
    # repli -- voir _resolve_by_date_amount ci-dessus) : un compte gele est
    # ici une explication plausible (l'utilisateur a peut-etre tente le
    # retrait mais son compte gele a empeche la creation meme de la
    # transaction). `locator_label` adapte le libelle du message a la voie
    # utilisee ("cette référence" ou "cette date et ce montant") sans
    # dupliquer toute la cascade de regles metier (gel/KYC/plafond) ci-dessous.
    context = {**({"transaction_reference": reference} if reference else {}), **(extra_context or {})}

    if wallet.status != "ACTIVE":
        return _account_frozen_outcome(wallet, reference or "", user_id_raw, still_pending=False)

    if not wallet.kyc_verified:
        return resolved(
            f"Je ne trouve aucun retrait avec {locator_label}. Votre vérification d'identité (KYC) "
            "n'est pas encore validée : c'est probablement pour cette raison que le retrait n'a "
            "jamais pu être initié. Terminez votre vérification KYC puis réessayez.",
            "KYC_REQUIRED",
            context,
        )

    if (
        wallet.monthly_limit is not None
        and wallet.total_withdrawals is not None
        and wallet.total_withdrawals >= wallet.monthly_limit
    ):
        return resolved(
            f"Je ne trouve aucun retrait avec {locator_label}. Vous avez atteint votre plafond de "
            f"retrait ({wallet.total_withdrawals}/{wallet.monthly_limit} {wallet.currency or ''} "
            "utilisés) : c'est probablement pour cette raison que le retrait n'a jamais pu être initié. "
            "Le plafond se réinitialise chaque mois.",
            "LIMIT_EXCEEDED",
            {
                **context,
                "total_withdrawals": float(wallet.total_withdrawals),
                "monthly_limit": float(wallet.monthly_limit),
            },
        )

    return escalate(
        f"Je ne trouve aucun retrait correspondant à {locator_label} sur votre compte. "
        "Je transmets cela à notre équipe technique.",
        "TRANSACTION_NOT_FOUND",
        "Wallet",
        "medium",
        {"user_id": user_id_raw, **context},
    )


def _build_success_message(tx: WalletTransaction, frozen_note: str) -> str:
    currency = (tx.currency or "").strip() or None

    message = "Votre retrait"
    if tx.amount is not None:
        message += f" de {tx.amount:.0f}" + (f" {currency}" if currency else "")
    message += " a bien été effectué"
    completed_at = format_datetime(tx.completed_at)
    if completed_at:
        message += f" le {completed_at}"
    if tx.provider:
        message += f" via {tx.provider}"
    if tx.phone_number:
        message += f" vers le numéro {tx.phone_number}"
    return message + "." + frozen_note


def _resolve_existing_transaction(wallet: Wallet, tx: WalletTransaction, reference: str) -> dict:
    # La transaction a un statut definitif ou en cours propre a elle : on
    # informe d'abord sur CE retrait precis, meme si le compte est gele
    # aujourd'hui (le gel peut etre survenu apres coup et n'explique pas un
    # evenement deja passe). Le gel est mentionne en complement (_frozen_note),
    # pas comme cause presumee -- sauf pour un retrait encore PENDING plus
    # bas, ou il reste une explication plausible du blocage.
    frozen_note = _frozen_note(wallet)

    if tx.status == "SUCCESS":
        currency = (tx.currency or "").strip() or None
        return resolved(
            _build_success_message(tx, frozen_note),
            "WITHDRAWAL_COMPLETED",
            {
                "transaction_reference": reference,
                "completed_at": tx.completed_at.isoformat() if tx.completed_at else None,
                "amount": float(tx.amount) if tx.amount is not None else None,
                "currency": currency,
                "provider": tx.provider,
                "phone_number": tx.phone_number,
                "account_frozen": wallet.status != "ACTIVE",
            },
        )

    if tx.status == "CANCELLED":
        completed_at = format_datetime(tx.completed_at)
        when = f" le {completed_at}" if completed_at else ""
        return resolved(
            f"Ce retrait a été annulé{when} et votre solde a été restauré." + frozen_note,
            "WITHDRAWAL_CANCELLED_BY_USER",
            {
                "transaction_reference": reference,
                "completed_at": tx.completed_at.isoformat() if tx.completed_at else None,
                "account_frozen": wallet.status != "ACTIVE",
            },
        )

    if tx.status == "FAILED":
        completed_at = format_datetime(tx.completed_at)
        when = f" le {completed_at}" if completed_at else ""
        return resolved(
            f"Ce retrait a échoué{when} chez le prestataire de paiement et votre solde a été "
            "automatiquement restauré." + frozen_note,
            "WITHDRAWAL_FAILED_REFUNDED",
            {
                "transaction_reference": reference,
                "completed_at": tx.completed_at.isoformat() if tx.completed_at else None,
                "error_code": tx.error_code,
                "account_frozen": wallet.status != "ACTIVE",
            },
        )

    if tx.status == "PENDING":
        return _resolve_pending_transaction(wallet, tx, reference)

    return escalate(
        "Le statut de ce retrait est inhabituel. Je transmets cela à notre équipe technique.",
        "UNKNOWN_STATUS",
        "Wallet",
        "medium",
        {"transaction_reference": reference, "status": tx.status},
    )


def _resolve_pending_transaction(wallet: Wallet, tx: WalletTransaction, reference: str) -> dict:
    # Ici, contrairement a SUCCESS/CANCELLED/FAILED, le gel EST une
    # explication plausible du blocage puisque le retrait n'est toujours pas
    # resolu : on la remonte comme cause presumee plutot qu'en simple note.
    if wallet.status != "ACTIVE":
        return _account_frozen_outcome(wallet, reference, str(wallet.user_id), still_pending=True)

    age_minutes = (datetime.now(timezone.utc) - tx.created_at).total_seconds() / 60
    duration = format_duration_minutes(age_minutes)
    requested_at = format_datetime(tx.created_at)
    requested_suffix = f" (demandé le {requested_at})" if requested_at else ""
    if age_minutes < WITHDRAWAL_PENDING_SLA_MINUTES:
        return resolved(
            f"Votre retrait est en cours de traitement chez votre opérateur Mobile Money depuis "
            f"{duration}{requested_suffix}, c'est normal à ce stade. Vous devriez le recevoir sous peu.",
            "PENDING_WITHIN_SLA",
            {"transaction_reference": reference, "age_minutes": round(age_minutes, 1)},
        )

    return escalate(
        f"Votre retrait est en attente depuis {duration}{requested_suffix}, ce qui est anormalement "
        "long. Je transmets cela à notre équipe technique.",
        "PENDING_BEYOND_SLA_NO_PROVIDER_RESPONSE",
        "Wallet",
        "high",
        {
            "transaction_reference": reference,
            "status": "PENDING",
            "age_minutes": round(age_minutes, 1),
            "provider_transaction_id": tx.provider_transaction_id,
        },
    )
