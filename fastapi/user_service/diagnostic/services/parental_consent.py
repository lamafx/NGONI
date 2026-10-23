"""Logique de resolution du diagnostic de consentement parental -- porte
manuelle de ParentalConsentService (ngoni-user-service). Toute evolution du
code PHP (nouveaux codes de rejet, nouvelle regle d'expiration...) doit etre
repercutee ici (voir README.md).

Recherche par child_id (pas parent_id) : c'est l'utilisateur mineur dont le
compte reste verrouille qui contacte generalement le support, pas le
parent."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from ...db import ParentalConsent
from ...outcomes import escalate, resolved
from ..formatting import format_datetime


def resolve_parental_consent(db: Session, user_id_raw: str) -> dict:
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

    consent = (
        db.query(ParentalConsent)
        .filter_by(child_id=user_id)
        .order_by(ParentalConsent.requested_at.desc())
        .first()
    )

    if consent is None:
        return resolved(
            "Je ne trouve aucune demande de consentement parental associée à votre compte. Si votre "
            "compte est bloqué pour cette raison, rendez-vous dans les réglages pour lancer une "
            "demande.",
            "NO_CONSENT_REQUEST_FOUND",
            {},
        )

    status = (consent.status or "").lower()
    expired = consent.request_expires_at is not None and consent.request_expires_at < datetime.utcnow()

    if status == "verified":
        return resolved(
            "Le consentement de votre parent a bien été validé. Votre compte devrait être débloqué ; "
            "si ce n'est pas le cas, je transmets cela à notre équipe technique.",
            "CONSENT_ALREADY_VERIFIED",
            {"verified_at": format_datetime(consent.verified_at)},
        )

    if status == "rejected":
        reason = consent.rejection_reason or consent.rejection_reason_code
        reason_suffix = f" Motif indiqué : {reason}." if reason else ""
        return resolved(
            f"La demande de consentement a été refusée par le parent renseigné.{reason_suffix} Vous "
            "pouvez soumettre une nouvelle demande avec les bonnes informations parentales.",
            "CONSENT_REJECTED",
            {"rejection_reason": consent.rejection_reason, "rejection_reason_code": consent.rejection_reason_code},
        )

    if status == "expired" or expired:
        return resolved(
            "Cette demande de consentement parental a expiré avant d'avoir été traitée par le parent. "
            "Vous pouvez en soumettre une nouvelle depuis les réglages de votre compte.",
            "CONSENT_EXPIRED",
            {"request_expires_at": format_datetime(consent.request_expires_at)},
        )

    if status == "pending":
        expires = format_datetime(consent.request_expires_at)
        expires_suffix = f", avant le {expires}" if expires else ""
        return resolved(
            "La demande de consentement parental est en attente de réponse de la part du parent "
            f"renseigné{expires_suffix}. Aucune action supplémentaire n'est nécessaire de votre côté "
            "pour l'instant.",
            "CONSENT_PENDING",
            {"request_expires_at": expires},
        )

    return escalate(
        "Le statut de la demande de consentement parental est inhabituel. Je transmets cela à notre "
        "équipe technique.",
        "UNKNOWN_STATUS",
        "User",
        "medium",
        {"status": consent.status},
    )
