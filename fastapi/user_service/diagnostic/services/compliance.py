"""Logique de resolution du diagnostic de blocage compliance -- porte
manuelle de ComplianceService/RequireNoHold (ngoni-user-service). Toute
evolution du code PHP (nouveau trigger, nouvelle action...) doit etre
repercutee ici (voir README.md)."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from ...db import ComplianceEvent, User
from ...outcomes import escalate, resolved
from ..formatting import format_datetime


def resolve_compliance_hold(db: Session, user_id_raw: str) -> dict:
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

    if not user.compliance_hold:
        return resolved(
            "Je ne trouve aucun blocage de conformité actif sur votre compte. Le problème vient "
            "probablement d'autre chose (KYC, suspension...).",
            "NO_ACTIVE_HOLD",
            {},
        )

    latest_event = (
        db.query(ComplianceEvent)
        .filter_by(user_id=user_id)
        .order_by(ComplianceEvent.created_at.desc())
        .first()
    )
    trigger = latest_event.trigger if latest_event else None
    action = (latest_event.action or "").lower() if latest_event else ""
    trigger_suffix = f" (motif : {trigger})" if trigger else ""

    if action == "suspension":
        return escalate(
            f"Votre compte fait l'objet d'un blocage de conformité{trigger_suffix} qui a été escaladé "
            "en suspension. Je transmets votre demande à notre équipe pour réexamen.",
            "HOLD_ESCALATED_TO_SUSPENSION",
            "User",
            "high",
            {"trigger": trigger, "action": action},
        )

    if action in ("manual_review", "enhanced_kyc"):
        return escalate(
            f"Votre compte est en attente de revue manuelle par notre équipe de conformité{trigger_suffix}. "
            "Je transmets votre demande pour accélérer l'examen.",
            "HOLD_REQUIRES_MANUAL_REVIEW",
            "User",
            "medium",
            {"trigger": trigger, "action": action},
        )

    if user.compliance_hold_until and user.compliance_hold_until > datetime.utcnow():
        until = format_datetime(user.compliance_hold_until)
        return resolved(
            f"Votre compte est temporairement bloqué pour vérification de conformité{trigger_suffix}, "
            f"jusqu'au {until}. Aucune action n'est requise, le blocage se lève automatiquement.",
            "HOLD_ACTIVE_WITH_DEADLINE",
            {"trigger": trigger, "compliance_hold_until": until},
        )

    return resolved(
        f"Votre compte est actuellement bloqué pour vérification de conformité{trigger_suffix}. Notre "
        "équipe traite ces blocages au cas par cas.",
        "HOLD_ACTIVE",
        {"trigger": trigger, "action": action},
    )
