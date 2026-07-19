import asyncio
import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.complaints.schemas import TicketCreateResponse
from app.domains.complaints.service import ComplaintService
from app.shared.embeddings import cosine_similarity, embed_query
from app.shared.logging_utils import redact_entities
from .adapter import HttpDiagnosticAdapter
from .audit_repository import DiagnosticAuditRepository
from .contracts import (
    CapabilitiesResponse,
    CapabilityProblemSummary,
    ClassifyDebugCandidate,
    ClassifyDebugRequest,
    ClassifyDebugResponse,
    DiagnosticResolveRequest,
    EscalateOutcome,
)
from .escalation import escalate_to_ticket
from .pipeline import DiagnosticPipeline, UnknownProblem
from .registry import CapabilityRegistry
from .schemas import DiagnosticQuery, DiagnosticResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/diagnostic', tags=['diagnostic'])


@router.post('/search', response_model=DiagnosticResult)
def search_diagnostic(payload: DiagnosticQuery, db: Session = Depends(get_db)):
    # get_db() (app/database.py) fournit une Session SQLAlchemy synchrone
    # (create_engine, pas create_async_engine) -- ce endpoint declarait a tort
    # AsyncSession/await, ce qui levait un TypeError a chaque appel (Session
    # n'est pas awaitable). Aligne sur le meme pattern synchrone que le reste
    # de ce fichier (escalate_diagnostic, get_pipeline...).
    query = text('SELECT symptom, diagnosis, next_steps FROM diagnostic_records WHERE symptom ILIKE :symptom LIMIT 1')
    result = db.execute(query, {'symptom': f'%{payload.symptom}%'})
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail='Diagnostic introuvable')
    return DiagnosticResult(**dict(row._mapping))


@lru_cache
def get_registry() -> CapabilityRegistry:
    """Registre partage pour tout le process (Phase 5 : services_registry.yaml
    + rafraichissement periodique -- voir registry.py)."""
    return CapabilityRegistry()


@lru_cache
def get_adapter() -> HttpDiagnosticAdapter:
    """Adapter HTTP partage pour tout le process (Phase 6, etape 25) : le
    disjoncteur qu'il porte doit accumuler ses echecs consecutifs A TRAVERS
    les requetes -- un Adapter recree a chaque appel (comme get_pipeline
    avant cette phase) aurait un disjoncteur qui ne s'ouvre jamais, chaque
    requete repartant avec un compteur a zero."""
    return HttpDiagnosticAdapter()


def get_pipeline(
    registry: CapabilityRegistry = Depends(get_registry),
    adapter: HttpDiagnosticAdapter = Depends(get_adapter),
    db: Session = Depends(get_db),
) -> DiagnosticPipeline:
    # DiagnosticAuditRepository, lui, est recree a chaque requete (lie a la
    # Session SQLAlchemy per-request de get_db, jamais partage) -- voir
    # audit_repository.py (Phase 6, etape 26).
    return DiagnosticPipeline(registry, adapter=adapter, audit_repository=DiagnosticAuditRepository(db))


@router.get('/capabilities', response_model=CapabilitiesResponse)
async def list_capabilities(registry: CapabilityRegistry = Depends(get_registry)):
    """Agrege tous les manifestes connus (voir docs/diagnostic-roadmap.md,
    Phase 2, etape 11). C'est la SEULE source que le Dialogue Manager doit
    consulter pour savoir quels (service, probleme) sont diagnosticables et
    quels champs ils exigent -- aucun registre statique cote Rasa."""
    await registry.ensure_loaded()
    return CapabilitiesResponse(
        problems=[
            CapabilityProblemSummary(
                service=routable.service,
                id=routable.problem.id,
                label=routable.problem.label,
                description=routable.problem.description,
                keywords=routable.problem.keywords,
                required_fields=routable.problem.required_fields,
                optional_fields=routable.problem.optional_fields,
                embedding=routable.embedding,
                example_embeddings=routable.example_embeddings,
            )
            for routable in registry.all_problems()
        ]
    )


@router.post('/debug/classify', response_model=ClassifyDebugResponse)
async def debug_classify(payload: ClassifyDebugRequest, registry: CapabilityRegistry = Depends(get_registry)):
    """Outil de debug/demo (audit qualite du code, fonctionnalite #10) :
    prend une phrase libre et retourne le score de similarite avec TOUS les
    problemes du catalogue, tries par score decroissant -- reproduit le
    calcul de base de _score_capabilities_embeddings (rasa/actions/diagnostic.py)
    sans le repli mots-cles ni le rescue par clause (qui dependent de l'etat
    de conversation, hors de portee d'un endpoint sans etat). Remplace les
    scripts jetables utilises pendant l'audit de classification (ex. la
    correction de withdrawal_pending vs compliance_hold_blocking) par un
    outil reutilisable, appelable en developpement comme en soutenance.
    """
    await registry.ensure_loaded()
    # Meme raisonnement que CapabilityRegistry._compute_all_embeddings
    # (registry.py) : embed_query() est un calcul CPU synchrone, l'appeler
    # directement dans cette coroutine bloquerait toute la boucle asyncio
    # (donc tout le process FastAPI) pendant son execution -- ce endpoint de
    # debug/demo doit rester reactif, y compris pendant une soutenance.
    message_embedding = await asyncio.to_thread(embed_query, payload.text)
    candidates: list[ClassifyDebugCandidate] = []
    for routable in registry.all_problems():
        candidate_vectors = ([routable.embedding] if routable.embedding else []) + routable.example_embeddings
        has_embedding = bool(candidate_vectors)
        score = max((cosine_similarity(message_embedding, v) for v in candidate_vectors), default=0.0)
        candidates.append(
            ClassifyDebugCandidate(
                service=routable.service,
                problem_id=routable.problem.id,
                label=routable.problem.label,
                score=score,
                has_embedding=has_embedding,
            )
        )
    candidates.sort(key=lambda c: -c.score)
    return ClassifyDebugResponse(text=payload.text, candidates=candidates)


@router.post('/escalate', response_model=TicketCreateResponse)
def escalate_diagnostic(
    payload: EscalateOutcome,
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(None, alias='X-User-ID'),
):
    """Relais generique vers le systeme de tickets existant (voir
    docs/diagnostic-roadmap.md, Phase 3, etape 18). N'importe quel appelant
    disposant deja d'un EscalateOutcome (le pipeline lui-meme pour le cas
    SERVICE_UNAVAILABLE, voir /resolve ci-dessous, ou un futur appelant
    externe) peut le transmettre ici pour obtenir un vrai ticket, sans
    dupliquer le mapping vers TicketCreateRequest. created_by reste
    'ai_auto_escalation' par defaut : un appel direct a cette route ne passe,
    par definition, par aucune confirmation utilisateur cote Rasa."""
    try:
        return escalate_to_ticket(ComplaintService.from_session(db), payload, user_id=x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/resolve')
async def resolve_diagnostic(
    payload: DiagnosticResolveRequest,
    pipeline: DiagnosticPipeline = Depends(get_pipeline),
    x_user_id: str = Header(..., alias='X-User-ID'),
    db: Session = Depends(get_db),
):
    """Point d'entree unique du Diagnostic Engine (voir docs/diagnostic-flow.md).

    Ce endpoint delegue integralement au DiagnosticPipeline pour la logique
    de routage/resolution, qui reste 100% generique. La SEULE chose faite ici
    en plus : quand le pipeline renvoie sa propre escalade de resilience
    (SERVICE_UNAVAILABLE -- un microservice injoignable, voir pipeline.py),
    un vrai ticket est cree automatiquement via /diagnostic/escalate, sans
    attendre de confirmation utilisateur (Phase 3, etape 19). Les escalades
    qui viennent du microservice lui-meme (ACCOUNT_FROZEN, TRANSACTION_NOT_FOUND...)
    ne sont PAS concernees : elles continuent de passer par la confirmation
    utilisateur deja geree cote Rasa -- ce n'est pas une politique generique
    du Engine, donc pas sa responsabilite de l'automatiser.

    L'identite de l'utilisateur voyage en header X-User-ID (meme convention
    que Kong -> wallet-service), jamais dans le corps de la requete cote
    Dialogue Manager.
    """
    logger.info(
        "[DIAG][ENGINE] session=%s stage=request_in service=%s problem=%s user=%s entities=%s",
        payload.session_id, payload.service, payload.problem, x_user_id, redact_entities(payload.entities),
    )
    try:
        outcome = await pipeline.resolve(x_user_id, payload)
    except UnknownProblem as exc:
        logger.warning(
            "[DIAG][ENGINE] session=%s stage=request_in result=404_UNKNOWN_PROBLEM error=%s",
            payload.session_id, exc,
        )
        raise HTTPException(
            status_code=404,
            detail=(
                f"Probleme '{exc.problem}' non reconnu pour le service '{exc.service}'. "
                "Verifiez que son Capability Manifest le declare bien."
            ),
        ) from exc

    if isinstance(outcome, EscalateOutcome) and outcome.escalation_reason == "SERVICE_UNAVAILABLE":
        try:
            ticket = escalate_to_ticket(
                ComplaintService.from_session(db),
                outcome,
                user_id=x_user_id,
                created_by="ai_auto_escalation",
            )
            DiagnosticAuditRepository(db).link_latest_escalation(
                session_id=payload.session_id, ticket_id=ticket.ticket_id
            )
        except ValueError:
            # Ne fait jamais echouer la reponse a l'utilisateur pour un
            # probleme de creation de ticket : il a deja son message
            # d'escalade, la tracabilite du ticket est secondaire.
            logger.warning("Echec de la creation automatique de ticket pour une escalade SERVICE_UNAVAILABLE", exc_info=True)

    logger.info(
        "[DIAG][ENGINE] session=%s stage=response_out outcome=%s",
        payload.session_id, outcome.outcome,
    )
    return outcome
