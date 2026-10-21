"""Routes d'ecriture pour l'espace Admin > Parametres (voir
frontfolder/src/pages/AdminSettingsPage.jsx). Protegees par
require_admin_auth, meme convention que domains/complaints/admin_router.py.

Rappel important (voir migrations/0015_system_parameters.sql et
api_admin_a_developper.md section 10) : ecrire ici trace l'intention et
l'identite de qui a demande le changement, mais ne modifie PAS encore le
comportement reel de Rasa/FastAPI -- ces seuils restent lus depuis des
constantes Python/YAML au demarrage des processus, jamais depuis cette
table. Le pont ("hot reload") reste a construire."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.shared.admin_auth import require_admin_auth
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from shared.admin_auth import require_admin_auth

from .schemas import SystemParameterHistoryResponse, SystemParameterResponse, SystemParameterUpdateRequest
from .service import ParameterOutOfRangeError, SystemParameterService, UnknownParameterError

router = APIRouter(
    prefix="/admin/settings",
    tags=["admin"],
    dependencies=[Depends(require_admin_auth)],
)


@router.get("/parameters", response_model=List[SystemParameterResponse])
def list_parameters(db: Session = Depends(get_db)):
    """Ne renvoie QUE les paramètres explicitement modifiés depuis l'admin --
    une liste vide signifie que tous les seuils sont encore à leur valeur par
    défaut (celle codée en dur côté Rasa/FastAPI, jamais dupliquée ici)."""
    return SystemParameterService.from_session(db).list_overrides()


@router.patch("/parameters/{param_id}", response_model=SystemParameterResponse)
def update_parameter(param_id: str, payload: SystemParameterUpdateRequest, db: Session = Depends(get_db)):
    service = SystemParameterService.from_session(db)
    try:
        return service.update(param_id, payload.value, payload.changed_by)
    except UnknownParameterError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ParameterOutOfRangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/parameters/history", response_model=List[SystemParameterHistoryResponse])
def list_parameter_history(param_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    return SystemParameterService.from_session(db).list_history(param_id=param_id)


@router.delete("/parameters/history")
def clear_parameter_history(param_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Purge le journal des modifications (tout, ou un seul paramètre avec
    `param_id`). Les valeurs courantes ne sont PAS touchées : effacer la trace
    d'un réglage ne remet pas ce réglage à sa valeur par défaut.

    Opération volontairement irréversible et sans corbeille -- c'est un
    journal d'audit : on l'archive avant de le vider, on ne compte pas sur ce
    service pour le restituer."""
    deleted = SystemParameterService.from_session(db).clear_history(param_id=param_id)
    return {"deleted": deleted}
