"""Annuaire des conseillers, cote administration (meme protection que les
autres routes /admin/*). Remplace le tableau statique AGENTS de
frontend/src/data/mockData.js -- voir api_admin_a_developper.md section 5."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.shared.admin_auth import require_admin_auth
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from shared.admin_auth import require_admin_auth

from .schemas import AgentCreateRequest, AgentResponse, AgentStatusUpdateRequest
from .service import AgentService, UnknownAgentError

router = APIRouter(
    prefix="/admin/agents",
    tags=["admin"],
    dependencies=[Depends(require_admin_auth)],
)


@router.get("/", response_model=List[AgentResponse])
def list_agents(db: Session = Depends(get_db)):
    return AgentService.from_session(db).list_agents()


@router.post("/", response_model=AgentResponse, status_code=201)
def create_agent(payload: AgentCreateRequest, db: Session = Depends(get_db)):
    return AgentService.from_session(db).create(
        payload.agent_id, payload.display_name, payload.role
    )


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    try:
        return AgentService.from_session(db).get_agent(agent_id)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail="Conseiller introuvable") from exc


@router.patch("/{agent_id}/status", response_model=AgentResponse)
def update_agent_status(
    agent_id: str, payload: AgentStatusUpdateRequest, db: Session = Depends(get_db)
):
    service = AgentService.from_session(db)
    try:
        return service.set_status(agent_id, payload.status)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail="Conseiller introuvable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
