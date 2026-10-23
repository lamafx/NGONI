"""Logique de resolution du diagnostic de suppression de compte -- porte
manuelle de ProfileController::deleteAccount/reactivateAccount
(ngoni-user-service). Toute evolution du code PHP (delai de grace, nouveaux
codes...) doit etre repercutee ici (voir README.md)."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from ...db import AccountDeletion
from ...outcomes import escalate, resolved
from ..formatting import format_datetime


def resolve_account_deletion(db: Session, user_id_raw: str) -> dict:
    try:
        user_id = uuid.UUID(user_id_raw)
    except ValueError:
        return escalate(
            "Identifiant utilisateur invalide.",
            "USER_NOT_FOUND",
            "User",
            "high",
            {"user_id": user_id_raw},
        )

    deletion = (
        db.query(AccountDeletion)
        .filter_by(user_id=user_id)
        .order_by(AccountDeletion.soft_deleted_at.desc())
        .first()
    )

    if deletion is None:
        return resolved(
            "Je ne trouve aucune procédure de suppression en cours sur votre compte : il n'a pas été "
            "supprimé.",
            "NOT_DELETED",
            {},
        )

    if deletion.hard_deleted_at is not None:
        # Purge definitive deja effectuee : rien a reactiver, reponse
        # definitive plutot qu'une escalade -- rien qu'une equipe humaine
        # pourrait changer, la suppression est irreversible par politique.
        return resolved(
            "Ce compte a été définitivement supprimé (délai de grâce de 30 jours écoulé) : il n'est "
            "plus possible de le récupérer, conformément à notre politique de confidentialité.",
            "CANNOT_REACTIVATE",
            {"hard_deleted_at": format_datetime(deletion.hard_deleted_at)},
        )

    scheduled = format_datetime(deletion.hard_delete_scheduled_for)

    if deletion.hard_delete_scheduled_for < datetime.utcnow():
        # Le delai de grace est ecoule mais la purge definitive (job planifie
        # cote ngoni-user-service) n'est pas encore passee -- etat transitoire
        # qui ne devrait pas durer, signale plutot que devine.
        return escalate(
            "Le délai de grâce de votre compte est écoulé, la suppression définitive n'a pas encore "
            "été appliquée de notre côté. Je transmets cela à notre équipe technique.",
            "GRACE_EXPIRED_PENDING_PURGE",
            "User",
            "medium",
            {"hard_delete_scheduled_for": scheduled},
        )

    reason_suffix = f" Motif indiqué : {deletion.deletion_reason}." if deletion.deletion_reason else ""
    return resolved(
        f"Votre compte est en cours de suppression.{reason_suffix} Vous êtes encore dans le délai de "
        f"grâce de 30 jours : reconnectez-vous avant le {scheduled} pour annuler la suppression et "
        "récupérer votre compte.",
        "WITHIN_GRACE_PERIOD",
        {"hard_delete_scheduled_for": scheduled, "deletion_reason": deletion.deletion_reason},
    )
