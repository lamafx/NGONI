"""Espace conseiller : la file des conversations, leur reprise en main, et
la reponse humaine. Meme protection que les autres routes d'administration
(header X-Internal-Secret, voir shared/admin_auth.py) -- ces routes exposent
l'integralite des messages des usagers, ce n'est pas une donnee publique.

Remplace ce que l'espace Agent du frontend simulait dans DemoStore/
localStorage (voir api_admin_a_developper.md section 4)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.domains.agents.service import AgentService
    from app.shared.admin_auth import get_admin_id, require_admin_auth
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from domains.agents.service import AgentService
    from shared.admin_auth import get_admin_id, require_admin_auth

from .models import ALLOWED_STATUSES
from .schemas import (
    AgentMessageRequest,
    AssignRequest,
    ConversationContextResponse,
    ConversationDetailResponse,
    ConversationSummaryResponse,
    MessageResponse,
    ResolveRequest,
)
from .service import ConversationNotFoundError, ConversationService, ConversationStateError

router = APIRouter(
    prefix="/admin/conversations",
    tags=["admin"],
    dependencies=[Depends(require_admin_auth)],
)


def _service(db: Session) -> ConversationService:
    return ConversationService.from_session(db)


@router.get("/", response_model=List[ConversationSummaryResponse])
def list_conversations(
    status: Optional[str] = Query(None, description=" | ".join(sorted(ALLOWED_STATUSES))),
    assigned_to: Optional[str] = Query(None),
    escalated: Optional[bool] = Query(None),
    unassigned: Optional[bool] = Query(
        None, description="Ne garder que les conversations qu'aucun conseiller n'a prises"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if status is not None and status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Statut inconnu : {status!r} (attendu : {', '.join(sorted(ALLOWED_STATUSES))})",
        )
    return _service(db).list_conversations(
        status=status,
        assigned_to=assigned_to,
        escalated=escalated,
        unassigned=unassigned,
        limit=limit,
        offset=offset,
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    try:
        return _service(db).get_detail(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation introuvable") from exc


@router.get("/{conversation_id}/context", response_model=ConversationContextResponse)
def get_conversation_context(conversation_id: str, db: Session = Depends(get_db)):
    """Resume de reprise pour le conseiller : pourquoi cette conversation lui
    arrive, ce que le moteur a deja tente, quels tickets existent deja."""
    try:
        return _service(db).build_context(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation introuvable") from exc


@router.post("/{conversation_id}/assign", response_model=ConversationSummaryResponse)
def assign_conversation(
    conversation_id: str,
    payload: AssignRequest,
    force: bool = Query(
        False, description="Reprendre une conversation déjà tenue par un autre conseiller"
    ),
    db: Session = Depends(get_db),
):
    """« Prendre en charge une demande » : a partir d'ici le bot ne repond
    plus sur cette conversation (voir ConversationService.is_muted) -- c'est
    le conseiller qui parle."""
    try:
        assigned = _service(db).assign(conversation_id, payload.agent_id, force=force)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation introuvable") from exc
    except ConversationStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    AgentService.from_session(db).touch(payload.agent_id)
    return assigned


@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=201)
def post_agent_message(
    conversation_id: str,
    payload: AgentMessageRequest,
    admin_id: Optional[str] = Depends(get_admin_id),
    db: Session = Depends(get_db),
):
    """Reponse humaine dans le fil. L'utilisateur la recoit via
    GET /conversations/{id}/updates (voir router.py) -- pas besoin de la
    faire transiter par Rasa, qui est justement mis en silence pendant la
    prise en charge."""
    agent_id = payload.agent_id or admin_id
    try:
        message = _service(db).post_agent_message(conversation_id, payload.text, agent_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation introuvable") from exc
    except ConversationStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if agent_id:
        AgentService.from_session(db).touch(agent_id)
    return message


@router.post("/{conversation_id}/resolve", response_model=ConversationSummaryResponse)
def resolve_conversation(
    conversation_id: str,
    payload: ResolveRequest,
    admin_id: Optional[str] = Depends(get_admin_id),
    db: Session = Depends(get_db),
):
    """Sort la conversation de la file. Le bot reprend la main au prochain
    message de l'utilisateur (voir record_user_message)."""
    agent_id = payload.agent_id or admin_id
    try:
        resolved = _service(db).resolve(conversation_id, agent_id, note=payload.note)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation introuvable") from exc
    if agent_id:
        AgentService.from_session(db).touch(agent_id)
    return resolved
