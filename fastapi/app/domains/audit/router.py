from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

try:
    from app.database import get_db
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db

from .schemas import AgentActionCreateRequest, AgentActionResponse
from .service import AgentActionService

router = APIRouter(prefix="/audit", tags=["audit"])


@router.post("/actions", response_model=AgentActionResponse, status_code=201)
def record_agent_action(payload: AgentActionCreateRequest, db: Session = Depends(get_db)):
    """Ingestion generique des decisions autonomes non couvertes par un audit
    specifique a un domaine (voir docs/15-modele-donnees.md). Appele
    notamment par le serveur d'actions Rasa (process externe, sans acces
    direct a la base) pour tracer ses propres decisions de classification --
    voir rasa/actions/diagnostic.py::_report_agent_action, qui traite cet
    appel en best-effort (ne bloque jamais une reponse utilisateur)."""
    service = AgentActionService.from_session(db)
    try:
        return service.record(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/actions", response_model=List[AgentActionResponse])
def list_agent_actions(
    domain: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    service = AgentActionService.from_session(db)
    return service.list_actions(domain=domain, session_id=session_id)
