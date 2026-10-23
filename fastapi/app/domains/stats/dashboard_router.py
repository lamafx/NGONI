"""Tableau de bord de l'espace Admin : KPI, séries, répartition des
intentions, activité récente, diagnostics exécutés, santé des services.

Même protection que les autres routes /admin/* (X-Internal-Secret).
Remplace `buildDashboardStats()` / `buildIntentDistribution()` /
`recentActivity` de frontend/src/data/mockData.js -- voir
api_admin_a_developper.md sections 2, 3, 7 et 8."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.domains.diagnostic.registry import SERVICES_REGISTRY_PATH, _load_services_from_yaml
    from app.shared.admin_auth import require_admin_auth
    from app.shared.rasa_client import RASA_PARSE_URL
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from domains.diagnostic.registry import SERVICES_REGISTRY_PATH, _load_services_from_yaml
    from shared.admin_auth import require_admin_auth
    from shared.rasa_client import RASA_PARSE_URL

from .dashboard_schemas import (
    ConversationVolumeResponse,
    DashboardSummaryResponse,
    DiagnosticProblemsResponse,
    DiagnosticRunsResponse,
    DiagnosticSessionDetail,
    DiagnosticSessionsResponse,
    IntentDistributionResponse,
    RecentActivityResponse,
    ServiceHealth,
    SystemHealthResponse,
)
from .dashboard_service import DEFAULT_PERIOD_DAYS, DashboardService

logger = logging.getLogger(__name__)

# Meme serveur que RASA_PARSE_URL (seule adresse Rasa configuree cote moteur).
RASA_STATUS_URL = RASA_PARSE_URL.rsplit("/model/parse", 1)[0] + "/status"

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_auth)])

# Sonde volontairement courte : la page d'administration ne doit pas rester
# bloquee plusieurs secondes parce qu'un microservice ne repond plus -- ne
# pas repondre DANS ce delai est precisement l'information cherchee.
HEALTH_TIMEOUT_SECONDS = 2.0


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    days: int = Query(DEFAULT_PERIOD_DAYS, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return DashboardService.from_session(db).summary(days=days)


@router.get("/dashboard/conversation-volume", response_model=ConversationVolumeResponse)
def dashboard_conversation_volume(
    days: int = Query(DEFAULT_PERIOD_DAYS, ge=1, le=90),
    db: Session = Depends(get_db),
):
    return DashboardService.from_session(db).conversation_volume(days=days)


@router.get("/dashboard/intent-distribution", response_model=IntentDistributionResponse)
def dashboard_intent_distribution(
    days: int = Query(DEFAULT_PERIOD_DAYS, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Volumétrie réelle par intention, telle que classée par le moteur au
    moment où il a répondu (voir app/main.py, POST /api/chat) -- pas une
    re-classification a posteriori."""
    return DashboardService.from_session(db).intent_distribution(days=days)


@router.get("/dashboard/recent-activity", response_model=RecentActivityResponse)
def dashboard_recent_activity(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return DashboardService.from_session(db).recent_activity(limit=limit)


@router.get("/diagnostics/runs", response_model=DiagnosticRunsResponse)
def diagnostic_runs(
    days: int = Query(DEFAULT_PERIOD_DAYS, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return DashboardService.from_session(db).diagnostic_runs(days=days)


@router.get("/diagnostics/problems", response_model=DiagnosticProblemsResponse)
def diagnostic_problems(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Bilan par probleme diagnosticable : ou le diagnostic aboutit, ou il
    escalade, et pour quelle cause (outcome_detail)."""
    return DashboardService.from_session(db).diagnostic_problems(days=days)


@router.get("/diagnostics/sessions", response_model=DiagnosticSessionsResponse)
def diagnostic_sessions(
    days: int = Query(30, ge=1, le=365),
    status: Optional[str] = Query(None, pattern="^(IN_PROGRESS|RESOLVED|ESCALATED)$"),
    service: Optional[str] = Query(None, max_length=64),
    problem: Optional[str] = Query(None, max_length=128),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return DashboardService.from_session(db).diagnostic_sessions(
        days=days, status=status, service=service, problem=problem, limit=limit, offset=offset
    )


@router.get("/diagnostics/sessions/{session_id}", response_model=DiagnosticSessionDetail)
def diagnostic_session_detail(session_id: str, db: Session = Depends(get_db)):
    detail = DashboardService.from_session(db).diagnostic_session_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session de diagnostic introuvable")
    return detail


@router.get("/system/health", response_model=SystemHealthResponse)
async def system_health(db: Session = Depends(get_db)):
    """Interroge réellement chaque dépendance plutôt que de dupliquer une
    logique de santé : PostgreSQL par une requête, Rasa par son endpoint
    d'analyse, et chaque microservice métier par le manifeste que le
    Diagnostic Engine lui demande déjà (`GET {base_url}/diagnostic/manifest`,
    voir registry.py) -- si ce manifeste ne répond pas, le diagnostic ne
    fonctionne pas pour ce service, c'est le seul signal qui compte ici."""
    services: List[ServiceHealth] = []

    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        services.append(
            ServiceHealth(
                name="PostgreSQL",
                status="operational",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )
    except Exception as error:
        services.append(ServiceHealth(name="PostgreSQL", status="down", detail=str(error)[:200]))

    async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
        started = time.perf_counter()
        try:
            # GET /status (modele charge) plutot que POST /model/parse : le
            # classifieur d'intentions passe par un LLM local (Qwen via
            # Ollama, ~9 s par phrase), une analyse de "ping" depassait donc
            # toujours HEALTH_TIMEOUT_SECONDS et Rasa s'affichait "down"
            # alors qu'il repondait -- en consommant au passage un appel LLM
            # a chaque ouverture du tableau de bord.
            response = await client.get(RASA_STATUS_URL)
            services.append(
                ServiceHealth(
                    name="Rasa (NLU + Core)",
                    status="operational" if response.status_code < 400 else "degraded",
                    detail=None if response.status_code < 400 else f"HTTP {response.status_code}",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            )
        except Exception as error:
            services.append(
                ServiceHealth(name="Rasa (NLU + Core)", status="down", detail=str(error)[:200])
            )

        # Meme source de verite que le Diagnostic Engine (services_registry.yaml,
        # relu a chaque appel) : un service ajoute au registre apparait ici sans
        # redemarrage, et la liste ne peut pas diverger de celle reellement routee.
        for service in _load_services_from_yaml(SERVICES_REGISTRY_PATH):
            started = time.perf_counter()
            try:
                response = await client.get(
                    f"{service.base_url}/diagnostic/manifest",
                    headers={"X-Internal-Secret": service.internal_secret},
                )
                services.append(
                    ServiceHealth(
                        name=f"{service.name} service",
                        status="operational" if response.status_code < 400 else "degraded",
                        detail=None if response.status_code < 400 else f"HTTP {response.status_code}",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                )
            except Exception as error:
                services.append(
                    ServiceHealth(
                        name=f"{service.name} service", status="down", detail=str(error)[:200]
                    )
                )

    # Statut global : le pire des statuts individuels. Une facade "tout va
    # bien" alors qu'une dependance est tombee est exactement ce que
    # l'ancienne liste codee en dur faisait.
    if any(service.status == "down" for service in services):
        overall = "down"
    elif any(service.status == "degraded" for service in services):
        overall = "degraded"
    else:
        overall = "operational"

    return SystemHealthResponse(
        checked_at=datetime.now(timezone.utc).isoformat(), status=overall, services=services
    )
