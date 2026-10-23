"""Logique de resolution du diagnostic de cadeau non recu -- porte manuelle
de GiftController / WalletService::processGiftSend (ngoni-wallet-service).

Un cadeau cree DEUX transactions liees dans le meme appel : GIFT_SENT cote
envoyeur (reference_id = ref) et GIFT_RECEIVED cote destinataire
(reference_id = ref + '-RCV'), toutes deux normalement creees en SUCCESS
d'un coup (voir WalletService::processGiftSend). L'anomalie diagnostiquee
ici est l'absence de la transaction jumelle apres que l'envoyeur ait bien
ete debite -- un cas rare (echec partiel entre les deux insertions), pas le
chemin normal."""

import uuid

from sqlalchemy.orm import Session

from ...db import WalletTransaction
from ...outcomes import escalate, resolved
from ..formatting import format_datetime

RECEIVED_SUFFIX = "-RCV"


def resolve_gift(db: Session, user_id_raw: str, reference: str) -> dict:
    try:
        user_id = uuid.UUID(user_id_raw)
    except ValueError:
        return escalate(
            "Identifiant utilisateur invalide.",
            "TRANSACTION_NOT_FOUND",
            "Wallet",
            "high",
            {"user_id": user_id_raw, "gift_reference": reference},
        )

    # Filtre par user_id : seul l'envoyeur du cadeau peut interroger sa propre
    # transaction GIFT_SENT par cette reference (evite qu'un utilisateur
    # devine la reference d'un cadeau qui n'est pas le sien).
    sent_tx = (
        db.query(WalletTransaction)
        .filter_by(user_id=user_id, type="GIFT_SENT", reference_id=reference)
        .first()
    )

    if sent_tx is None:
        return escalate(
            "Je ne trouve aucun cadeau envoyé correspondant à cette référence sur votre compte. "
            "Je transmets cela à notre équipe technique.",
            "TRANSACTION_NOT_FOUND",
            "Wallet",
            "medium",
            {"user_id": user_id_raw, "gift_reference": reference},
        )

    if sent_tx.status != "SUCCESS":
        return escalate(
            "Le statut de ce cadeau est inhabituel. Je transmets cela à notre équipe technique.",
            "UNKNOWN_STATUS",
            "Wallet",
            "medium",
            {"gift_reference": reference, "status": sent_tx.status},
        )

    # La transaction jumelle appartient au DESTINATAIRE (un autre user_id) :
    # on la retrouve uniquement par reference, sans filtre user_id ici.
    received_tx = (
        db.query(WalletTransaction)
        .filter_by(type="GIFT_RECEIVED", reference_id=reference + RECEIVED_SUFFIX)
        .first()
    )

    if received_tx is None:
        sent_at = format_datetime(sent_tx.completed_at)
        sent_suffix = f" le {sent_at}" if sent_at else ""
        return escalate(
            f"Votre cadeau a bien été débité de votre compte{sent_suffix}, mais je ne retrouve pas "
            "trace de sa réception par le destinataire. Je transmets cela à notre équipe technique.",
            "SENT_WITHOUT_RECEIVED_PAIR",
            "Wallet",
            "high",
            {
                "gift_reference": reference,
                "sent_status": sent_tx.status,
                "sent_completed_at": sent_tx.completed_at.isoformat() if sent_tx.completed_at else None,
            },
        )

    if received_tx.status == "SUCCESS":
        message = "Votre cadeau a bien été livré"
        completed_at = format_datetime(received_tx.completed_at)
        if completed_at:
            message += f" le {completed_at}"
        message += " : le destinataire l'a bien reçu."
        return resolved(
            message,
            "GIFT_DELIVERED",
            {
                "gift_reference": reference,
                "completed_at": received_tx.completed_at.isoformat() if received_tx.completed_at else None,
            },
        )

    return escalate(
        "Le cadeau a été envoyé mais sa réception n'est pas encore confirmée. "
        "Je transmets cela à notre équipe technique.",
        "UNKNOWN_STATUS",
        "Wallet",
        "medium",
        {"gift_reference": reference, "received_status": received_tx.status},
    )
