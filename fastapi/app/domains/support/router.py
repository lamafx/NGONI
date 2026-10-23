"""Dossier client du conseiller humain (espace Agent).

  GET  /admin/support/users/{user_id}                   dossier complet
  GET  /admin/support/documents/{document_id}/image     image de la piece
  POST /admin/support/users/{user_id}/identity-decision valider / refuser
  POST /admin/support/users/{user_id}/notes             note interne

Le dossier assemble ce qui appartient a chaque service : le compte et son
historique KYC (user_service), le portefeuille (wallet_service), les pieces
recues, conversations, reclamations et le journal des actions (moteur).
Toute consultation nominative et toute decision sont tracees dans
ia.agent_actions (domaine `support_humain`) : qui, quand, sur quoi.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.domains.audit.models import AgentAction
    from app.domains.conversations.service import ConversationService
    from app.domains.identity_documents.models import (
        REVIEW_APPROVED,
        REVIEW_PENDING,
        REVIEW_REJECTED,
        IdentityDocument,
        document_summary,
    )
    from app.shared.admin_auth import require_admin_auth
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from domains.audit.models import AgentAction
    from domains.conversations.service import ConversationService
    from domains.identity_documents.models import (
        REVIEW_APPROVED,
        REVIEW_PENDING,
        REVIEW_REJECTED,
        IdentityDocument,
        document_summary,
    )
    from shared.admin_auth import require_admin_auth

from . import client
from .comparison import compare

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/support", tags=["admin"], dependencies=[Depends(require_admin_auth)])

DOMAIN = "support_humain"


def _audit(db: Session, user_id: str, action_type: str, agent_id: str, *, conversation_id=None,
           input_data=None, output_data=None) -> None:
    db.add(
        AgentAction(
            user_id=user_id,
            session_id=conversation_id,
            domain=DOMAIN,
            action_type=action_type,
            input_data={"agent_id": agent_id, **(input_data or {})},
            output_data=output_data,
        )
    )
    db.commit()


def _remote(fetch, user_id: str):
    """(donnees, erreur) : un service indisponible n'empeche pas d'afficher le
    reste du dossier -- l'erreur est dite a l'ecran."""
    try:
        return fetch(user_id), None
    except client.ServiceUnavailable as exc:
        return None, str(exc)


def _documents(db: Session, user_id: str):
    return (
        db.query(IdentityDocument)
        .filter(IdentityDocument.user_id == user_id)
        .order_by(IdentityDocument.created_at.desc())
        .limit(20)
        .all()
    )


def build_dossier(db: Session, user_id: str) -> dict:
    account, account_error = _remote(client.get_account, user_id)
    wallet, wallet_error = _remote(client.get_wallet, user_id)
    documents = _documents(db, user_id)
    latest_accepted = next((d for d in documents if d.accepted), None)
    conversations = ConversationService.from_session(db)
    actions = (
        db.query(AgentAction)
        .filter(AgentAction.user_id == user_id, AgentAction.domain == DOMAIN)
        .order_by(AgentAction.created_at.desc())
        .limit(30)
        .all()
    )
    return {
        "user_id": user_id,
        "account": account,
        "account_error": account_error,
        "wallet": wallet,
        "wallet_error": wallet_error,
        "documents": [document_summary(d) for d in documents],
        "comparison": compare(latest_accepted.fields, account) if latest_accepted else [],
        "compared_document_id": str(latest_accepted.id) if latest_accepted else None,
        "conversations": [c.model_dump() for c in conversations.history_for_user(user_id, limit=10)],
        "tickets": [t.model_dump() for t in conversations.tickets_for_user(user_id, limit=10)],
        "actions": [
            {
                "action_type": a.action_type,
                "agent_id": (a.input_data or {}).get("agent_id"),
                "detail": (a.input_data or {}).get("reason") or (a.input_data or {}).get("text"),
                "conversation_id": a.session_id,
                "at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in actions
        ],
    }


@router.get("/users/{user_id}")
def get_dossier(
    user_id: str,
    agent_id: Optional[str] = Query(None, max_length=100, description="Trace la consultation si renseigne."),
    conversation_id: Optional[str] = Query(None, max_length=200),
    db: Session = Depends(get_db),
):
    dossier = build_dossier(db, user_id)
    if dossier["account"] is None and dossier["account_error"] is None and not dossier["documents"]:
        raise HTTPException(status_code=404, detail="Aucun compte ni dossier pour cet identifiant")
    if agent_id:
        _audit(db, user_id, "dossier_consulte", agent_id, conversation_id=conversation_id)
        dossier = build_dossier(db, user_id)
    return dossier


@router.get("/documents")
def list_documents(
    status: str = Query(REVIEW_PENDING, pattern="^(pending|approved|rejected)$"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Pieces acceptees par le filtre, par etat d'examen -- la file « a
    verifier » du conseiller."""
    documents = (
        db.query(IdentityDocument)
        .filter(IdentityDocument.accepted.is_(True), IdentityDocument.review_status == status)
        .order_by(IdentityDocument.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {key: value for key, value in document_summary(d).items() if key not in ("fields", "checks")}
        for d in documents
    ]


@router.get("/documents/{document_id}/image")
def document_image(document_id: str, db: Session = Depends(get_db)):
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Piece introuvable") from exc
    document = db.get(IdentityDocument, doc_uuid)
    if document is None or document.image is None:
        raise HTTPException(status_code=404, detail="Piece introuvable")
    return Response(
        content=document.image,
        media_type=document.content_type or "image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


class DecisionRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=100)
    decision: Literal["approved", "rejected"]
    reason: Optional[str] = Field(default=None, max_length=500)
    document_id: Optional[str] = None
    conversation_id: Optional[str] = Field(default=None, max_length=200)


@router.post("/users/{user_id}/identity-decision")
def identity_decision(user_id: str, payload: DecisionRequest, db: Session = Depends(get_db)):
    if payload.decision == "rejected" and not (payload.reason or "").strip():
        raise HTTPException(status_code=422, detail="Un refus doit être motivé.")

    document = None
    if payload.document_id:
        try:
            document = db.get(IdentityDocument, uuid.UUID(payload.document_id))
        except ValueError:
            document = None
        if document is None or document.user_id != user_id:
            raise HTTPException(status_code=404, detail="Pièce introuvable pour ce compte")
        if document.review_status != REVIEW_PENDING:
            raise HTTPException(status_code=409, detail="Cette pièce a déjà été traitée.")

    try:
        result = client.kyc_decision(
            user_id,
            payload.decision,
            payload.reason,
            str(document.kyc_submission_id) if document is not None and document.kyc_submission_id else None,
        )
    except client.ServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if document is not None:
        document.review_status = REVIEW_APPROVED if payload.decision == "approved" else REVIEW_REJECTED
        document.reviewed_by = payload.agent_id
        document.reviewed_at = datetime.now(timezone.utc)
        document.review_reason = payload.reason
        db.commit()

    _audit(
        db,
        user_id,
        "identite_validee" if payload.decision == "approved" else "identite_refusee",
        payload.agent_id,
        conversation_id=payload.conversation_id or (document.conversation_id if document else None),
        input_data={"document_id": payload.document_id, "reason": payload.reason},
        output_data={"kyc_status": result.get("kyc_status"), "submission_id": result.get("submission_id")},
    )
    logger.info("[SUPPORT] %s : identite %s par %s", user_id, payload.decision, payload.agent_id)
    return build_dossier(db, user_id)


class NoteRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(default=None, max_length=200)


@router.post("/users/{user_id}/notes", status_code=201)
def add_note(user_id: str, payload: NoteRequest, db: Session = Depends(get_db)):
    _audit(
        db,
        user_id,
        "note_interne",
        payload.agent_id,
        conversation_id=payload.conversation_id,
        input_data={"text": payload.text.strip()},
    )
    return build_dossier(db, user_id)
