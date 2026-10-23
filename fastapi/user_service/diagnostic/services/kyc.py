"""Logique de resolution du diagnostic KYC -- porte manuelle de
KycController/KycService (ngoni-user-service). Toute evolution du code PHP
(nouveau statut, nouvelle regle de niveau...) doit etre repercutee ici si on
veut continuer a tester ce cas localement (voir README.md)."""

import uuid

from sqlalchemy.orm import Session

from ...db import KycSubmission, User
from ...outcomes import escalate, resolved
from ..formatting import format_datetime


def resolve_kyc_status(db: Session, user_id_raw: str) -> dict:
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

    if (user.kyc_status or "").upper() in ("VERIFIED", "APPROVED"):
        return resolved(
            f"Votre vérification d'identité est déjà validée (niveau {user.kyc_level}). "
            "Aucune action n'est nécessaire de votre côté.",
            "KYC_ALREADY_VERIFIED",
            {"kyc_level": user.kyc_level, "kyc_status": user.kyc_status},
        )

    latest = (
        db.query(KycSubmission)
        .filter_by(user_id=user_id)
        .order_by(KycSubmission.created_at.desc())
        .first()
    )

    if latest is None:
        return resolved(
            "Je ne trouve aucune demande de vérification d'identité envoyée pour votre compte. "
            "Rendez-vous dans les réglages de votre compte pour démarrer votre KYC.",
            "KYC_NOT_STARTED",
            {"kyc_status": user.kyc_status},
        )

    status = (latest.status or "").lower()

    if status == "pending":
        return resolved(
            "Votre demande de vérification d'identité est bien reçue et en cours d'examen par notre "
            "équipe. Vous recevrez une notification dès qu'elle sera traitée.",
            "KYC_UNDER_REVIEW",
            {"kyc_level": latest.level, "submitted_at": format_datetime(latest.created_at)},
        )

    if status == "rejected":
        reason_suffix = f" Motif indiqué : {latest.rejection_reason}." if latest.rejection_reason else ""
        return resolved(
            f"Votre dernière demande de vérification d'identité a été refusée.{reason_suffix} "
            "Vous pouvez soumettre une nouvelle demande en corrigeant le document concerné.",
            "KYC_REJECTED",
            {"kyc_level": latest.level, "rejection_reason": latest.rejection_reason},
        )

    if status == "approved":
        # La derniere soumission est approuvee mais users.kyc_status ne le
        # reflete pas encore (verifie plus haut) -- incoherence entre les
        # deux tables, pas un vrai etat KYC a expliquer a l'utilisateur.
        return escalate(
            "Votre dernière demande a été approuvée mais votre statut ne semble pas encore à jour. "
            "Je transmets cela à notre équipe technique pour vérification.",
            "KYC_STATUS_MISMATCH",
            "User",
            "medium",
            {"kyc_level": latest.level, "user_kyc_status": user.kyc_status},
        )

    return escalate(
        "Le statut de votre vérification d'identité est inhabituel. Je transmets cela à notre équipe technique.",
        "UNKNOWN_STATUS",
        "User",
        "medium",
        {"kyc_status": user.kyc_status, "submission_status": latest.status},
    )
