"""Routes d'ecriture pour l'espace Admin > Parametres (voir
frontfolder/src/pages/AdminSettingsPage.jsx). Protegees par
require_admin_auth, meme convention que domains/complaints/admin_router.py.

Ecrire ici trace l'intention et l'identite de qui a demande le changement.
Pour les seuils de LIVE_PARAMETERS (service.py), c'est aussi ce qui change
le comportement reel du moteur : Rasa les relit via GET /settings/engine
(engine_router ci-dessous), FastAPI via live.py. Les autres seuils restent
lus depuis leurs constantes Python/YAML au demarrage des processus -- pour
eux, le pont reste a construire (voir migrations/0015_system_parameters.sql)."""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.shared.admin_auth import require_admin_auth
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from shared.admin_auth import require_admin_auth

from . import live
from .schemas import SystemParameterHistoryResponse, SystemParameterResponse, SystemParameterUpdateRequest
from .service import ParameterOutOfRangeError, SystemParameterService, UnknownParameterError

router = APIRouter(
    prefix="/admin/settings",
    tags=["admin"],
    dependencies=[Depends(require_admin_auth)],
)

# Lecture seule, SANS require_admin_auth : c'est le conteneur Rasa qui
# l'appelle (rasa/components/dynamic_fallback_classifier.py), comme les
# actions appellent deja /faq/search ou /diagnostic/resolve. N'expose que
# des seuils de classification, jamais l'identite de qui les a ecrits.
engine_router = APIRouter(prefix="/settings", tags=["settings"])


@engine_router.get("/engine", response_model=Dict[str, float])
def engine_parameters(db: Session = Depends(get_db)):
    """Seuils relus à chaud par le moteur et surchargés depuis l'admin. Un
    objet vide signifie que le moteur applique ses valeurs par défaut."""
    return SystemParameterService.from_session(db).live_overrides()


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
        updated = service.update(param_id, payload.value, payload.changed_by)
        live.invalidate()
        return updated
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
