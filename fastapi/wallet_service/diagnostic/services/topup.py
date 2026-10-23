"""Logique de resolution du diagnostic de recharge (topup) -- porte manuelle
de TopupController (ngoni-wallet-service). Meme structure que service.py
(retrait) : voir ce fichier pour le detail des conventions partagees
(ACCOUNT_FROZEN, notes de gel, etc.)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ...db import Wallet, WalletTransaction
from ...outcomes import escalate, resolved
from ..formatting import format_datetime, format_duration_minutes

# Une recharge mobile money est generalement reglee en quelques minutes
# (contrairement a un retrait, jusqu'a 120 min) -- aucune valeur de SLA
# documentee cote wallet-service a ce jour pour topup : hypothese de depart,
# a valider avec l'equipe wallet-service avant mise en production.
TOPUP_PENDING_SLA_MINUTES = 15


def _to_major_units(amount) -> float | None:
    # WalletTransaction.amount est stocke en CENTIMES uniquement pour les
    # lignes TOPUP (voir WalletTransaction::toMajorUnits cote PHP -- un
    # incident de production a deja eu lieu ici : une recharge de 500
    # affichee comme 50000). Ne jamais exposer ce montant sans cette
    # conversion.
    if amount is None:
        return None
    return float(amount) / 100


def resolve_topup(db: Session, user_id_raw: str, reference: str) -> dict:
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

    tx = (
        db.query(WalletTransaction)
        .filter_by(wallet_id=wallet.id, type="TOPUP", reference_id=reference)
        .first()
    )

    if tx is None:
        return _resolve_missing_transaction(wallet, reference, user_id_raw)

    return _resolve_existing_transaction(wallet, tx, reference)


def _frozen_note(wallet: Wallet) -> str:
    if wallet.status == "ACTIVE":
        return ""
    since = format_datetime(wallet.frozen_at)
    since_suffix = f" depuis le {since}" if since else ""
    note = f" Notez par ailleurs que votre portefeuille est actuellement gelé (statut : {wallet.status}){since_suffix}"
    if wallet.frozen_reason:
        note += f", raison indiquée : {wallet.frozen_reason}"
    return note + "."


def _resolve_missing_transaction(wallet: Wallet, reference: str, user_id_raw: str) -> dict:
    if wallet.status != "ACTIVE":
        since = format_datetime(wallet.frozen_at)
        since_suffix = f" depuis le {since}" if since else ""
        reason_suffix = f" Raison indiquée : {wallet.frozen_reason}." if wallet.frozen_reason else ""
        return escalate(
            f"Votre portefeuille est actuellement gelé (statut : {wallet.status}){since_suffix}.{reason_suffix} "
            "C'est probablement pour cette raison que cette recharge n'a jamais pu être initiée. "
            "Je transmets cela à notre équipe technique pour réexamen.",
            "ACCOUNT_FROZEN",
            "Wallet",
            "high",
            {
                "user_id": user_id_raw,
                "transaction_reference": reference,
                "status": wallet.status,
                "frozen_at": wallet.frozen_at.isoformat() if wallet.frozen_at else None,
            },
        )

    return escalate(
        "Je ne trouve aucune recharge correspondant à cette référence sur votre compte. "
        "Je transmets cela à notre équipe technique.",
        "TRANSACTION_NOT_FOUND",
        "Wallet",
        "medium",
        {"user_id": user_id_raw, "transaction_reference": reference},
    )


def _resolve_existing_transaction(wallet: Wallet, tx: WalletTransaction, reference: str) -> dict:
    # Meme principe que le retrait (service.py) : un statut definitif propre
    # a cette transaction prime sur l'etat de gel actuel du compte, qui n'est
    # mentionne qu'en complement -- sauf pour une recharge encore en attente,
    # ou le gel reste une explication plausible du blocage.
    frozen_note = _frozen_note(wallet)
    amount = _to_major_units(tx.amount)
    currency = (tx.currency or "").strip() or None

    if tx.status == "SUCCESS":
        message = "Votre recharge"
        if amount is not None:
            message += f" de {amount:.0f}" + (f" {currency}" if currency else "")
        message += " a bien été créditée sur votre solde"
        completed_at = format_datetime(tx.completed_at)
        if completed_at:
            message += f" le {completed_at}"
        message += "." + frozen_note
        return resolved(
            message,
            "TOPUP_COMPLETED",
            {
                "transaction_reference": reference,
                "completed_at": tx.completed_at.isoformat() if tx.completed_at else None,
                "amount": amount,
                "currency": currency,
                "provider": tx.provider,
                "account_frozen": wallet.status != "ACTIVE",
            },
        )

    if tx.status == "FAILED":
        completed_at = format_datetime(tx.completed_at)
        when = f" le {completed_at}" if completed_at else ""
        return resolved(
            f"Cette recharge a échoué{when} chez le prestataire de paiement : aucun montant n'a été "
            "débité de votre moyen de paiement." + frozen_note,
            "TOPUP_FAILED_NOT_DEBITED",
            {
                "transaction_reference": reference,
                "completed_at": tx.completed_at.isoformat() if tx.completed_at else None,
                "error_code": tx.error_code,
                "account_frozen": wallet.status != "ACTIVE",
            },
        )

    if tx.status in ("PENDING", "PROCESSING"):
        return _resolve_pending_transaction(wallet, tx, reference)

    return escalate(
        "Le statut de cette recharge est inhabituel. Je transmets cela à notre équipe technique.",
        "UNKNOWN_STATUS",
        "Wallet",
        "medium",
        {"transaction_reference": reference, "status": tx.status},
    )


def _resolve_pending_transaction(wallet: Wallet, tx: WalletTransaction, reference: str) -> dict:
    if wallet.status != "ACTIVE":
        since = format_datetime(wallet.frozen_at)
        since_suffix = f" depuis le {since}" if since else ""
        reason_suffix = f" Raison indiquée : {wallet.frozen_reason}." if wallet.frozen_reason else ""
        return escalate(
            f"Votre portefeuille est actuellement gelé (statut : {wallet.status}){since_suffix}.{reason_suffix} "
            "C'est probablement pour cette raison que cette recharge reste bloquée en attente. "
            "Je transmets cela à notre équipe technique pour réexamen.",
            "ACCOUNT_FROZEN",
            "Wallet",
            "high",
            {
                "transaction_reference": reference,
                "status": wallet.status,
                "frozen_at": wallet.frozen_at.isoformat() if wallet.frozen_at else None,
            },
        )

    age_minutes = (datetime.now(timezone.utc) - tx.created_at).total_seconds() / 60
    duration = format_duration_minutes(age_minutes)
    requested_at = format_datetime(tx.created_at)
    requested_suffix = f" (demandée le {requested_at})" if requested_at else ""
    if age_minutes < TOPUP_PENDING_SLA_MINUTES:
        return resolved(
            f"Votre recharge est en cours de traitement chez votre opérateur Mobile Money depuis "
            f"{duration}{requested_suffix}, c'est normal à ce stade. Elle devrait être créditée sous peu.",
            "PENDING_WITHIN_SLA",
            {"transaction_reference": reference, "age_minutes": round(age_minutes, 1)},
        )

    return escalate(
        f"Votre recharge est en attente depuis {duration}{requested_suffix}, ce qui est anormalement "
        "long. Je transmets cela à notre équipe technique.",
        "PENDING_BEYOND_SLA_NO_PROVIDER_RESPONSE",
        "Wallet",
        "high",
        {
            "transaction_reference": reference,
            "status": tx.status,
            "age_minutes": round(age_minutes, 1),
            "provider_transaction_id": tx.provider_transaction_id,
        },
    )
