"""API « support » de user_service : ce que le back-office d'un conseiller
humain lit et ecrit sur un compte. Le Diagnostic Engine n'y accede pas --
seul le moteur, pour le compte d'un conseiller authentifie par le secret
partage (voir app/domains/support).

  GET  /api/v1/support/users/{user_id}                 profil + historique KYC
  POST /api/v1/support/users/{user_id}/kyc-submissions nouvelle piece recue
  POST /api/v1/support/users/{user_id}/kyc-decision    decision du conseiller

La decision suit le cycle reel du KYC : la soumission en attente passe
`approved` (ou `rejected`) et `users.kyc_status` suit. C'est exactement ce que
relit ensuite le diagnostic `kyc_status_issue` (services/kyc.py) : l'usager
qui redemande a l'assistant obtient la reponse a jour, sans rien de scripte.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.database import get_db

from .security import require_internal_secret

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/support",
    tags=["support"],
    dependencies=[Depends(require_internal_secret)],
)

NIVEAU_APRES_VALIDATION = "level_1"


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _parse_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Compte introuvable") from exc


def _submissions(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT id, level, status, rejection_reason, reviewed_at, created_at "
            "FROM users.kyc_submissions WHERE user_id = :id ORDER BY created_at DESC"
        ),
        {"id": user_id},
    ).mappings()
    return [
        {
            "id": str(row["id"]),
            "level": row["level"],
            "status": row["status"],
            "rejection_reason": row["rejection_reason"],
            "reviewed_at": _iso(row["reviewed_at"]),
            "created_at": _iso(row["created_at"]),
        }
        for row in rows
    ]


@router.get("/users/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db)):
    uid = _parse_id(user_id)
    row = db.execute(
        text(
            """
            SELECT u.id, u.username, u.display_name, u.phone_number, u.city, u.language,
                   u.date_of_birth, u.status, u.kyc_status, u.kyc_level, u.role,
                   u.is_certified, u.is_ngoni_plus, u.compliance_hold,
                   u.followers_count, u.following_count, u.videos_count,
                   u.created_at, u.last_active_at, u.phone_verified_at,
                   c.name AS country
            FROM users.users u
            LEFT JOIN users.countries c ON c.id = u.country_id
            WHERE u.id = :id
            """
        ),
        {"id": uid},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    return {
        "user_id": str(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "phone_number": row["phone_number"],
        "city": row["city"],
        "country": row["country"],
        "language": row["language"],
        "date_of_birth": row["date_of_birth"].isoformat() if row["date_of_birth"] else None,
        "status": row["status"],
        "kyc_status": row["kyc_status"],
        "kyc_level": row["kyc_level"],
        "role": row["role"],
        "is_certified": row["is_certified"],
        "is_ngoni_plus": row["is_ngoni_plus"],
        "compliance_hold": row["compliance_hold"],
        "followers_count": row["followers_count"],
        "following_count": row["following_count"],
        "videos_count": row["videos_count"],
        "created_at": _iso(row["created_at"]),
        "last_active_at": _iso(row["last_active_at"]),
        "phone_verified_at": _iso(row["phone_verified_at"]),
        "kyc_submissions": _submissions(db, uid),
    }


class SubmissionRequest(BaseModel):
    level: str = Field(default=NIVEAU_APRES_VALIDATION, max_length=32)


@router.post("/users/{user_id}/kyc-submissions", status_code=201)
def open_submission(user_id: str, payload: SubmissionRequest, db: Session = Depends(get_db)):
    """Nouvelle piece d'identite recue : une soumission `pending` est ouverte
    (le diagnostic repond alors « en cours d'examen »). Une soumission deja
    en attente est reutilisee plutot que dupliquee."""
    uid = _parse_id(user_id)
    if db.execute(text("SELECT 1 FROM users.users WHERE id = :id"), {"id": uid}).first() is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    existing = db.execute(
        text("SELECT id FROM users.kyc_submissions WHERE user_id = :id AND status = 'pending' "
             "ORDER BY created_at DESC LIMIT 1"),
        {"id": uid},
    ).first()
    if existing:
        return {"submission_id": str(existing[0]), "created": False}
    submission_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.execute(
        text(
            "INSERT INTO users.kyc_submissions (id, user_id, level, status, created_at, updated_at) "
            "VALUES (:sid, :uid, :level, 'pending', :now, :now)"
        ),
        {"sid": submission_id, "uid": uid, "level": payload.level, "now": now},
    )
    db.commit()
    logger.info("[SUPPORT] soumission KYC ouverte user=%s submission=%s", uid, submission_id)
    return {"submission_id": str(submission_id), "created": True}


class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: Optional[str] = Field(default=None, max_length=500)
    submission_id: Optional[str] = None


@router.post("/users/{user_id}/kyc-decision")
def decide(user_id: str, payload: DecisionRequest, db: Session = Depends(get_db)):
    uid = _parse_id(user_id)
    if payload.decision == "rejected" and not (payload.reason or "").strip():
        raise HTTPException(status_code=422, detail="Un refus doit etre motive")
    if db.execute(text("SELECT 1 FROM users.users WHERE id = :id"), {"id": uid}).first() is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    target = None
    if payload.submission_id:
        target = db.execute(
            text("SELECT id, level FROM users.kyc_submissions WHERE id = :sid AND user_id = :uid"),
            {"sid": payload.submission_id, "uid": uid},
        ).first()
    if target is None:
        target = db.execute(
            text("SELECT id, level FROM users.kyc_submissions WHERE user_id = :uid AND status = 'pending' "
                 "ORDER BY created_at DESC LIMIT 1"),
            {"uid": uid},
        ).first()

    try:
        if target is None:
            submission_id = uuid.uuid4()
            db.execute(
                text(
                    "INSERT INTO users.kyc_submissions "
                    "(id, user_id, level, status, rejection_reason, reviewed_at, created_at, updated_at) "
                    "VALUES (:sid, :uid, :level, :status, :reason, :now, :now, :now)"
                ),
                {"sid": submission_id, "uid": uid, "level": NIVEAU_APRES_VALIDATION,
                 "status": payload.decision, "reason": payload.reason, "now": now},
            )
        else:
            submission_id = target[0]
            db.execute(
                text(
                    "UPDATE users.kyc_submissions SET status = :status, rejection_reason = :reason, "
                    "reviewed_at = :now, updated_at = :now WHERE id = :sid"
                ),
                {"status": payload.decision, "reason": payload.reason, "now": now, "sid": submission_id},
            )
        if payload.decision == "approved":
            db.execute(
                text("UPDATE users.users SET kyc_status = 'VERIFIED', kyc_level = :level, updated_at = :now "
                     "WHERE id = :uid"),
                {"level": target[1] if target else NIVEAU_APRES_VALIDATION, "now": now, "uid": uid},
            )
        else:
            db.execute(
                text("UPDATE users.users SET kyc_status = 'REJECTED', updated_at = :now WHERE id = :uid"),
                {"now": now, "uid": uid},
            )
        db.commit()
    except ProgrammingError as exc:
        db.rollback()
        # Droits d'ecriture absents sur le schema `users` (voir README,
        # « Droits du back-office support ») : le dire clairement plutot
        # qu'une erreur 500 opaque.
        logger.error("[SUPPORT] ecriture refusee sur users.* : %s", exc.orig)
        raise HTTPException(
            status_code=503,
            detail="Ecriture refusee par la base (droits du back-office support non accordes).",
        ) from exc

    logger.info("[SUPPORT] decision KYC user=%s decision=%s", uid, payload.decision)
    return {
        "user_id": str(uid),
        "submission_id": str(submission_id),
        "decision": payload.decision,
        "kyc_status": "VERIFIED" if payload.decision == "approved" else "REJECTED",
    }
