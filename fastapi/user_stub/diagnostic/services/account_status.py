"""Logique de resolution du diagnostic de statut de compte -- porte manuelle
de ProfileController::adminSuspend/adminBan/adminUnsuspend/adminUnban
(ngoni-user-service). Toute evolution du code PHP doit etre repercutee ici
(voir README.md)."""

import uuid

from sqlalchemy.orm import Session

from ...db import User
from ...outcomes import escalate, resolved
from ..formatting import format_datetime


def resolve_account_status(db: Session, user_id_raw: str) -> dict:
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

    user = db.query(User).filter_by(id=user_id).first()
    if user is None:
        return escalate(
            "Je ne retrouve pas votre compte. Je transmets cela à notre équipe technique.",
            "USER_NOT_FOUND",
            "User",
            "high",
            {"user_id": user_id_raw},
        )

    status = (user.status or "").upper()

    if status == "ACTIVE":
        return resolved(
            "Votre compte NGONI est actif, sans restriction de notre côté. Si vous n'arrivez pas à "
            "vous connecter, le problème vient probablement de l'authentification (mot de passe, "
            "session) plutôt que de votre profil.",
            "ACCOUNT_NOT_RESTRICTED",
            {"status": user.status},
        )

    if status == "SUSPENDED":
        since = format_datetime(user.suspended_at)
        since_suffix = f" depuis le {since}" if since else ""
        reason_suffix = f" Motif indiqué : {user.suspension_reason}." if user.suspension_reason else ""
        return resolved(
            f"Votre compte est actuellement suspendu{since_suffix}.{reason_suffix} Une suspension est "
            "temporaire ; contactez notre support si vous pensez qu'il y a une erreur.",
            "ACCOUNT_SUSPENDED",
            {"status": user.status, "suspension_reason": user.suspension_reason, "suspended_at": since},
        )

    if status == "BANNED":
        since = format_datetime(user.banned_at)
        since_suffix = f" depuis le {since}" if since else ""
        reason_suffix = f" Motif indiqué : {user.ban_reason}." if user.ban_reason else ""
        return escalate(
            f"Votre compte est banni{since_suffix}.{reason_suffix} Cette décision nécessite un "
            "réexamen humain. Je transmets votre demande à notre équipe.",
            "ACCOUNT_BANNED",
            "User",
            "high",
            {"status": user.status, "ban_reason": user.ban_reason, "banned_at": since},
        )

    return escalate(
        "Le statut de votre compte est inhabituel. Je transmets cela à notre équipe technique.",
        "UNKNOWN_STATUS",
        "User",
        "medium",
        {"status": user.status},
    )
