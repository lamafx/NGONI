"""Diagnostics du portefeuille ajoutes pour couvrir les demandes courantes du
support (portefeuille gele, fonds en attente, coins, achat et vente de
videos). Resolubles a partir du seul compte : aucune reference a demander --
la derniere operation du type concerne fait foi."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...outcomes import escalate, resolved
from ..formatting import format_datetime


def _fcfa(amount) -> str:
    return f"{float(amount or 0):,.0f} FCFA".replace(",", " ")


def _wallet(db: Session, user_id_raw: str):
    try:
        user_id = uuid.UUID(user_id_raw)
    except ValueError:
        return None, escalate("Identifiant utilisateur invalide.", "WALLET_NOT_FOUND", "Wallet", "high",
                              {"user_id": user_id_raw})
    wallet = db.execute(
        text("SELECT id, balance, pending_balance, currency, status, frozen_reason, frozen_at "
             "FROM wallet.wallets WHERE user_id = :uid"),
        {"uid": user_id},
    ).mappings().first()
    if wallet is None:
        return None, escalate(
            "Je ne retrouve pas de portefeuille associé à votre compte. Je transmets cela à notre équipe technique.",
            "WALLET_NOT_FOUND", "Wallet", "high", {"user_id": user_id_raw},
        )
    return wallet, None


def _latest(db: Session, wallet_id, kind: str):
    return db.execute(
        text("SELECT reference_id, status, amount, created_at, completed_at FROM wallet.wallet_transactions "
             "WHERE wallet_id = :wid AND type = :type ORDER BY created_at DESC NULLS LAST LIMIT 1"),
        {"wid": wallet_id, "type": kind},
    ).mappings().first()


def resolve_wallet_frozen(db: Session, user_id_raw: str) -> dict:
    wallet, error = _wallet(db, user_id_raw)
    if error:
        return error
    if (wallet["status"] or "").upper() == "ACTIVE" and not wallet["frozen_reason"]:
        return resolved(f"Votre portefeuille est actif et utilisable. Solde disponible : {_fcfa(wallet['balance'])}.",
                        "WALLET_ACTIVE")
    return escalate(
        f"Votre portefeuille est {wallet['status'].lower()}"
        + (f" depuis le {format_datetime(wallet['frozen_at'])}" if wallet["frozen_at"] else "")
        + (f" (motif : {wallet['frozen_reason']})" if wallet["frozen_reason"] else "")
        + ". Seule l'équipe conformité peut le débloquer : je lui transmets votre demande.",
        "WALLET_FROZEN", "Wallet", "high",
        {"status": wallet["status"], "frozen_reason": wallet["frozen_reason"]},
    )


def resolve_pending_balance(db: Session, user_id_raw: str) -> dict:
    wallet, error = _wallet(db, user_id_raw)
    if error:
        return error
    pending = float(wallet["pending_balance"] or 0)
    if pending <= 0:
        return resolved(
            f"Aucun fonds n'est en attente sur votre portefeuille. Solde disponible : {_fcfa(wallet['balance'])}.",
            "NO_PENDING_FUNDS",
        )
    return resolved(
        f"{_fcfa(pending)} sont en attente de validation sur votre portefeuille (gains récents en cours de "
        f"sécurisation). Ils rejoindront votre solde disponible ({_fcfa(wallet['balance'])}) à la fin du délai.",
        "PENDING_FUNDS", {"pending_balance": pending},
    )


def resolve_coin_purchase(db: Session, user_id_raw: str) -> dict:
    wallet, error = _wallet(db, user_id_raw)
    if error:
        return error
    tx = _latest(db, wallet["id"], "COIN_PURCHASE")
    if tx is None:
        return resolved("Aucun achat de coins n'est enregistré sur votre portefeuille.", "NO_COIN_PURCHASE")
    status = (tx["status"] or "").upper()
    if status == "SUCCESS":
        return resolved(
            f"Votre achat de coins du {format_datetime(tx['created_at'])} ({_fcfa(tx['amount'])}, réf. "
            f"{tx['reference_id']}) est bien crédité.",
            "COINS_CREDITED", {"reference": tx["reference_id"]},
        )
    if status == "FAILED":
        return resolved(
            f"Votre achat de coins du {format_datetime(tx['created_at'])} a échoué : vous n'avez pas été débité.",
            "COIN_PURCHASE_FAILED", {"reference": tx["reference_id"]},
        )
    return resolved(
        f"Votre achat de coins du {format_datetime(tx['created_at'])} est encore en cours de traitement chez le "
        "prestataire de paiement. Il sera crédité dès confirmation.",
        "COIN_PURCHASE_PENDING", {"reference": tx["reference_id"]},
    )


def resolve_video_purchase(db: Session, user_id_raw: str) -> dict:
    wallet, error = _wallet(db, user_id_raw)
    if error:
        return error
    tx = _latest(db, wallet["id"], "VIDEO_PURCHASE")
    if tx is None:
        return resolved("Aucun achat de vidéo n'est enregistré sur votre compte.", "NO_VIDEO_PURCHASE")
    status = (tx["status"] or "").upper()
    if status == "SUCCESS":
        return resolved(
            f"Votre achat de vidéo du {format_datetime(tx['created_at'])} (réf. {tx['reference_id']}) est confirmé : "
            "la vidéo est débloquée. Si elle reste verrouillée, fermez puis rouvrez l'application.",
            "VIDEO_UNLOCKED", {"reference": tx["reference_id"]},
        )
    if status == "FAILED":
        return resolved("Le paiement de cette vidéo a échoué : vous n'avez pas été débité, vous pouvez réessayer.",
                        "VIDEO_PURCHASE_FAILED", {"reference": tx["reference_id"]})
    return resolved("Le paiement de la vidéo est en cours de confirmation. Elle sera débloquée dès validation.",
                    "VIDEO_PURCHASE_PENDING", {"reference": tx["reference_id"]})


def resolve_video_sale_revenue(db: Session, user_id_raw: str) -> dict:
    wallet, error = _wallet(db, user_id_raw)
    if error:
        return error
    row = db.execute(
        text("SELECT count(*) AS n, coalesce(sum(amount), 0) AS total, max(created_at) AS last_at "
             "FROM wallet.wallet_transactions WHERE wallet_id = :wid AND type = 'VIDEO_SALE' AND status = 'SUCCESS'"),
        {"wid": wallet["id"]},
    ).mappings().first()
    if not row["n"]:
        return resolved(
            "Aucune vente de vidéo n'est encore enregistrée sur votre portefeuille. Les revenus apparaissent dès "
            "qu'un utilisateur achète une de vos vidéos payantes.",
            "NO_VIDEO_SALES",
        )
    return resolved(
        f"{row['n']} vente(s) de vidéo créditée(s) pour {_fcfa(row['total'])}, la dernière le "
        f"{format_datetime(row['last_at'])}. Ces revenus sont dans votre solde.",
        "VIDEO_SALES_CREDITED", {"count": row["n"], "total": float(row["total"])},
    )
