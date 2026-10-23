"""Diagnostics du compte ajoutes pour couvrir les demandes courantes du support
(certification, Ngoni+, telephone, moyen de retrait, carte NGONI, parrainage,
avertissements). Meme contrat que kyc.py : chaque fonction lit l'etat reel du
compte et renvoie RESOLVED (explication) ou ESCALATE (incoherence a traiter
par un humain)."""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...outcomes import escalate, resolved
from ..formatting import format_datetime
from ._common import load_user

# Au-dela, le compte est suspendu automatiquement (politique de moderation).
STRIKES_BEFORE_SUSPENSION = 3


def _expired(moment) -> bool:
    """Date passee ? Les colonnes du schema `users` melangent dates avec et
    sans fuseau (UTC) : on compare chacune a l'horloge de meme nature."""
    if moment is None:
        return False
    now = datetime.now(timezone.utc)
    return moment < (now if moment.tzinfo else now.replace(tzinfo=None))


def resolve_certification(db: Session, user_id_raw: str) -> dict:
    user, error = load_user(db, user_id_raw)
    if error:
        return error
    latest = db.execute(
        text("SELECT type, status, reason, reviewed_at, created_at FROM users.user_certifications "
             "WHERE user_id = :id ORDER BY created_at DESC LIMIT 1"),
        {"id": user["id"]},
    ).mappings().first()
    if user["is_certified"]:
        return resolved("Votre compte est bien certifié : le badge est actif sur votre profil.",
                        "CERTIFICATION_ACTIVE", {"type": latest["type"] if latest else None})
    if latest is None:
        return resolved(
            "Aucune demande de certification n'a été envoyée pour votre compte. Vous pouvez la faire "
            "depuis les réglages de votre profil, rubrique « Certification ».",
            "CERTIFICATION_NOT_REQUESTED",
        )
    status = (latest["status"] or "").lower()
    if status == "pending":
        return resolved(
            f"Votre demande de certification du {format_datetime(latest['created_at'])} est en cours d'examen. "
            "Vous serez notifié dès qu'elle sera traitée.",
            "CERTIFICATION_UNDER_REVIEW",
        )
    if status == "rejected":
        motif = f" Motif : {latest['reason']}." if latest["reason"] else ""
        return resolved(f"Votre demande de certification a été refusée.{motif} Vous pouvez en soumettre une nouvelle.",
                        "CERTIFICATION_REJECTED", {"reason": latest["reason"]})
    return escalate(
        "Votre certification est approuvée mais le badge n'apparaît pas encore sur votre compte. "
        "Je transmets à l'équipe pour mise à jour.",
        "CERTIFICATION_BADGE_MISSING", "User", "low", {"certification_status": latest["status"]},
    )


def resolve_ngoni_plus(db: Session, user_id_raw: str) -> dict:
    user, error = load_user(db, user_id_raw)
    if error:
        return error
    sub = db.execute(
        text("SELECT plan_type, status, expires_at, cancelled_at FROM users.subscriptions "
             "WHERE user_id = :id ORDER BY created_at DESC LIMIT 1"),
        {"id": user["id"]},
    ).mappings().first()
    if sub is None:
        return resolved("Votre compte n'a pas d'abonnement Ngoni+. Vous pouvez souscrire depuis l'onglet Ngoni+.",
                        "NGONI_PLUS_NONE")
    status = (sub["status"] or "").lower()
    if status == "active":
        if _expired(sub["expires_at"]):
            return escalate(
                "Votre abonnement Ngoni+ apparaît actif mais sa date de fin est dépassée. Je transmets à "
                "l'équipe pour vérifier le renouvellement.",
                "NGONI_PLUS_EXPIRED_BUT_ACTIVE", "Subscription", "medium",
                {"expires_at": format_datetime(sub["expires_at"])},
            )
        if not user["is_ngoni_plus"]:
            return escalate(
                "Votre abonnement Ngoni+ est actif mais les avantages ne sont pas activés sur votre compte. "
                "Je transmets à l'équipe pour correction.",
                "NGONI_PLUS_BENEFITS_MISSING", "Subscription", "medium", {"plan": sub["plan_type"]},
            )
        fin = f" jusqu'au {format_datetime(sub['expires_at'])}" if sub["expires_at"] else ""
        return resolved(f"Votre abonnement Ngoni+ ({sub['plan_type']}) est actif{fin}.", "NGONI_PLUS_ACTIVE",
                        {"plan": sub["plan_type"]})
    if status == "cancelled":
        quand = f" le {format_datetime(sub['cancelled_at'])}" if sub["cancelled_at"] else ""
        return resolved(f"Votre abonnement Ngoni+ a été annulé{quand}. Vous pouvez vous réabonner à tout moment.",
                        "NGONI_PLUS_CANCELLED")
    return resolved("Votre abonnement Ngoni+ est arrivé à échéance. Renouvelez-le depuis l'onglet Ngoni+.",
                    "NGONI_PLUS_EXPIRED", {"status": sub["status"]})


def resolve_phone_verification(db: Session, user_id_raw: str) -> dict:
    user, error = load_user(db, user_id_raw)
    if error:
        return error
    if not user["phone_number"]:
        return resolved("Aucun numéro de téléphone n'est enregistré sur votre compte. Ajoutez-le dans vos réglages.",
                        "PHONE_MISSING")
    if user["phone_verified_at"] is None:
        return resolved(
            "Votre numéro de téléphone n'est pas encore vérifié. Demandez un nouveau code de vérification depuis "
            "vos réglages : le code est valable quelques minutes.",
            "PHONE_NOT_VERIFIED",
        )
    return resolved(f"Votre numéro de téléphone est vérifié depuis le {format_datetime(user['phone_verified_at'])}.",
                    "PHONE_VERIFIED")


def resolve_payout_destination(db: Session, user_id_raw: str) -> dict:
    user, error = load_user(db, user_id_raw)
    if error:
        return error
    dest = db.execute(
        text("SELECT method, label, status, rejection_reason, created_at FROM users.payout_destinations "
             "WHERE user_id = :id ORDER BY is_default DESC, created_at DESC LIMIT 1"),
        {"id": user["id"]},
    ).mappings().first()
    if (user["kyc_status"] or "").upper() not in ("VERIFIED", "APPROVED"):
        return resolved(
            "Pour ajouter un moyen de retrait, votre vérification d'identité doit d'abord être validée. "
            "C'est l'étape qui bloque actuellement.",
            "PAYOUT_REQUIRES_KYC", {"kyc_status": user["kyc_status"]},
        )
    if dest is None:
        return resolved("Aucun moyen de retrait n'est enregistré. Ajoutez-en un depuis votre portefeuille.",
                        "PAYOUT_NOT_CONFIGURED")
    status = (dest["status"] or "").lower()
    if status in ("pending", "pending_verification"):
        return resolved(f"Votre moyen de retrait ({dest['method']}) est en cours de vérification.",
                        "PAYOUT_UNDER_REVIEW")
    if status == "rejected":
        motif = f" Motif : {dest['rejection_reason']}." if dest["rejection_reason"] else ""
        return resolved(f"Votre moyen de retrait ({dest['method']}) a été refusé.{motif}", "PAYOUT_REJECTED")
    return resolved(f"Votre moyen de retrait ({dest['method']}) est actif.", "PAYOUT_ACTIVE")


def resolve_ngoni_card(db: Session, user_id_raw: str) -> dict:
    user, error = load_user(db, user_id_raw)
    if error:
        return error
    card = db.execute(
        text("SELECT status, issued_at, expires_at FROM users.ngoni_cards WHERE user_id = :id "
             "ORDER BY created_at DESC LIMIT 1"),
        {"id": user["id"]},
    ).mappings().first()
    if card is None:
        return resolved(
            "Aucune carte NGONI n'a été émise pour votre compte. Elle est proposée une fois votre identité vérifiée.",
            "NGONI_CARD_NOT_ISSUED",
        )
    if _expired(card["expires_at"]):
        return resolved(f"Votre carte NGONI a expiré le {format_datetime(card['expires_at'])}. Demandez-en une nouvelle.",
                        "NGONI_CARD_EXPIRED")
    return resolved(f"Votre carte NGONI est {card['status']}.", "NGONI_CARD_ACTIVE", {"status": card["status"]})


def resolve_referral(db: Session, user_id_raw: str) -> dict:
    user, error = load_user(db, user_id_raw)
    if error:
        return error
    rows = db.execute(
        text("SELECT status, count(*) AS n, coalesce(sum(reward_cents), 0) AS cents FROM users.referrals "
             "WHERE referrer_id = :id GROUP BY status"),
        {"id": user["id"]},
    ).mappings().all()
    if not rows:
        return resolved("Aucun parrainage n'est enregistré avec votre code. Partagez-le depuis votre profil.",
                        "REFERRAL_NONE")
    counts = {row["status"]: row["n"] for row in rows}
    pending = counts.get("pending", 0)
    completed = counts.get("completed", 0)
    if pending and not completed:
        return resolved(
            f"Vous avez {pending} filleul(s) en attente : la récompense est versée quand le filleul a terminé "
            "son inscription et sa première activité.",
            "REFERRAL_PENDING", {"pending": pending},
        )
    total = sum(row["cents"] for row in rows) / 100
    return resolved(f"{completed} parrainage(s) validé(s), {total:.0f} de récompense créditée.", "REFERRAL_REWARDED",
                    {"completed": completed, "pending": pending})


def resolve_account_warnings(db: Session, user_id_raw: str) -> dict:
    user, error = load_user(db, user_id_raw)
    if error:
        return error
    strikes = user["strike_count"] or 0
    if strikes == 0:
        return resolved("Votre compte n'a reçu aucun avertissement : il est en règle.", "NO_STRIKES")
    restants = STRIKES_BEFORE_SUSPENSION - strikes
    if restants <= 0:
        return escalate(
            f"Votre compte cumule {strikes} avertissements, le seuil de suspension est atteint. "
            "Je transmets à l'équipe de modération pour examen.",
            "STRIKES_THRESHOLD_REACHED", "Moderation", "high", {"strike_count": strikes},
        )
    return resolved(
        f"Votre compte a reçu {strikes} avertissement(s). Au-delà de {STRIKES_BEFORE_SUSPENSION}, le compte est "
        f"suspendu : il vous en reste {restants} avant suspension. Respectez les règles de la communauté.",
        "STRIKES_WARNING", {"strike_count": strikes},
    )
