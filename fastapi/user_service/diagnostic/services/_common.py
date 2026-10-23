"""Chargement du compte, commun aux diagnostics qui lisent users.users en SQL
direct (colonnes non mappees par db.User)."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...outcomes import escalate

USER_COLUMNS = (
    "id, username, status, kyc_status, phone_number, phone_verified_at, is_certified, "
    "is_ngoni_plus, ngoni_plus_plan, ngoni_plus_status, ngoni_plus_end_date, strike_count, payout_method"
)


def load_user(db: Session, user_id_raw: str):
    """(compte, None) ou (None, reponse d'escalade USER_NOT_FOUND)."""
    try:
        user_id = uuid.UUID(user_id_raw)
    except ValueError:
        return None, escalate("Identifiant utilisateur invalide.", "USER_NOT_FOUND", "User", "high",
                              {"user_id": user_id_raw})
    row = db.execute(text(f"SELECT {USER_COLUMNS} FROM users.users WHERE id = :id"), {"id": user_id}).mappings().first()
    if row is None:
        return None, escalate(
            "Je ne retrouve pas votre compte. Je transmets cela à notre équipe technique.",
            "USER_NOT_FOUND", "User", "high", {"user_id": user_id_raw},
        )
    return row, None
