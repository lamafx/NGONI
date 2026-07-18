"""Pipeline generique du Diagnostic Engine (voir docs/diagnostic-flow.md,
section "Pipeline d'execution du Engine").

Ce fichier ne contient et ne doit jamais contenir de logique metier : toutes
les etapes ci-dessous (lookup, validation de completude, invocation,
normalisation) sont strictement identiques quel que soit le service ou le
probleme traite. La seule reaction "intelligente" presente ici -- escalader
automatiquement si le microservice cible est injoignable -- n'est pas une
regle metier : c'est une politique de resilience generique, appliquee de la
meme facon a n'importe quel service (voir contracts/diagnostic/README.md, §11
de docs/diagnostic-flow.md, "Compatibilite microservices").

Phase 6 (etape 26) : chaque appel a resolve() est trace via un
DiagnosticAuditRepository optionnel -- absent (None) dans les tests qui ne
montent pas de base de donnees (voir tests/test_diagnostic_pipeline.py), pour
ne pas leur imposer une dependance qu'ils n'ont jamais eue.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Union

from .adapter import DiagnosticInvocationError, HttpDiagnosticAdapter
from .audit_repository import DiagnosticAuditRepository
from .contracts import (
    DiagnosticInvocationRequest,
    DiagnosticResolveRequest,
    EscalateOutcome,
    EscalationPayload,
    NeedMoreInfoOutcome,
    ResolvedOutcome,
)
from .registry import CapabilityRegistry

logger = logging.getLogger(__name__)

DiagnosticOutcome = Union[ResolvedOutcome, EscalateOutcome, NeedMoreInfoOutcome]


def _outcome_detail(outcome: DiagnosticOutcome) -> str | None:
    """Le seul champ variable selon le type d'issue -- resolution_code,
    escalation_reason, ou missing_fields joints. Utilise a la fois pour les
    logs (_describe_outcome) et pour la colonne outcome_detail de
    DiagnosticAuditLog (voir Phase 6, etape 26) : une seule definition de ce
    qui compte comme "detail" d'une issue, pas deux formats a maintenir en
    parallele."""
    if isinstance(outcome, ResolvedOutcome):
        return outcome.resolution_code
    if isinstance(outcome, EscalateOutcome):
        return outcome.escalation_reason
    return ", ".join(outcome.missing_fields) or None


def _describe_outcome(outcome: DiagnosticOutcome) -> str:
    if isinstance(outcome, NeedMoreInfoOutcome):
        return f"missing_fields={outcome.missing_fields}"
    label = "resolution_code" if isinstance(outcome, ResolvedOutcome) else "escalation_reason"
    return f"{label}={_outcome_detail(outcome)}"


class UnknownProblem(Exception):
    """Le couple (service, problem) demande n'est declare par aucun manifeste connu."""

    def __init__(self, service: str, problem: str) -> None:
        self.service = service
        self.problem = problem
        super().__init__(f"Probleme inconnu: service={service!r} problem={problem!r}")


class DiagnosticPipeline:
    def __init__(
        self,
        registry: CapabilityRegistry,
        adapter: HttpDiagnosticAdapter | None = None,
        audit_repository: DiagnosticAuditRepository | None = None,
    ) -> None:
        self._registry = registry
        self._adapter = adapter or HttpDiagnosticAdapter()
        # None dans les tests qui ne montent pas de DB (voir docstring du
        # module) : la tracabilite est un besoin de Phase 6, jamais une
        # dependance dure du pipeline lui-meme.
        self._audit_repository = audit_repository

    def _record_audit(
        self,
        *,
        trace_id: str,
        session_id: str,
        user_id: str,
        service: str,
        problem: str,
        called_endpoint: str | None,
        entities: dict,
        outcome: DiagnosticOutcome,
        latency_ms: int | None,
    ) -> None:
        if self._audit_repository is None:
            return
        # Une panne d'ecriture (DB indisponible, contrainte violee...) ne
        # doit jamais faire echouer la reponse deja calculee pour
        # l'utilisateur -- la tracabilite est secondaire par rapport au
        # service rendu, meme politique que escalate_to_ticket dans
        # router.py pour SERVICE_UNAVAILABLE.
        try:
            self._audit_repository.record(
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                service=service,
                problem=problem,
                called_endpoint=called_endpoint,
                entities=entities,
                outcome=outcome.outcome,
                outcome_detail=_outcome_detail(outcome),
                latency_ms=latency_ms,
            )
        except Exception:
            logger.warning(
                "[DIAG][ENGINE] session=%s trace_id=%s stage=audit result=WRITE_FAILED",
                session_id, trace_id, exc_info=True,
            )

    async def resolve(self, user_id: str, request: DiagnosticResolveRequest) -> DiagnosticOutcome:
        await self._registry.ensure_loaded()

        # 1. Lookup — remplace le switch(service, problem) par une lecture de dictionnaire.
        target = self._registry.lookup(request.service, request.problem)
        if target is None:
            logger.warning(
                "[DIAG][ENGINE] session=%s stage=lookup result=UNKNOWN service=%s problem=%s",
                request.session_id, request.service, request.problem,
            )
            raise UnknownProblem(request.service, request.problem)

        # Genere ici (pas seulement au moment de l'invocation HTTP) pour que
        # CHAQUE branche loggee ci-dessous -- y compris NEED_MORE_INFO, qui
        # n'appelle jamais le microservice -- ait un trace_id coherent dans
        # l'audit log.
        trace_id = str(uuid.uuid4())

        # 2. Validation generique de completude : un ensemble de cles attendu
        #    contre un ensemble de cles fourni, jamais une regle metier.
        required = {field.name for field in target.problem.required_fields}
        provided = set(request.entities.keys())
        missing = sorted(required - provided)
        if missing:
            logger.info(
                "[DIAG][ENGINE] session=%s stage=validate result=NEED_MORE_INFO missing_fields=%s",
                request.session_id, missing,
            )
            outcome = NeedMoreInfoOutcome(missing_fields=missing)
            self._record_audit(
                trace_id=trace_id, session_id=request.session_id, user_id=user_id,
                service=request.service, problem=request.problem, called_endpoint=None,
                entities=request.entities, outcome=outcome, latency_ms=None,
            )
            return outcome

        allowed = required | {field.name for field in target.problem.optional_fields}
        filtered_entities = {k: v for k, v in request.entities.items() if k in allowed}

        invocation = DiagnosticInvocationRequest(
            session_id=request.session_id,
            trace_id=trace_id,
            user_id=user_id,
            problem_id=request.problem,
            entities=filtered_entities,
        )
        called_endpoint = f"{target.base_url}{target.problem.endpoint.path}"

        logger.info(
            "[DIAG][ENGINE] session=%s trace_id=%s stage=invoke target=%s entities=%s",
            request.session_id, invocation.trace_id, called_endpoint, filtered_entities,
        )

        # 3. Invocation du microservice proprietaire du probleme + normalisation
        #    (l'Adapter valide deja la reponse contre l'enveloppe standard).
        started_at = time.monotonic()
        try:
            outcome = await self._adapter.invoke(target, invocation)
        except DiagnosticInvocationError as exc:
            # Politique de resilience generique : un service injoignable ou
            # non conforme au contrat ne doit jamais bloquer l'utilisateur en
            # silence. On escalade automatiquement plutot que de renvoyer une
            # erreur brute au chatbot.
            logger.warning(
                "[DIAG][ENGINE] session=%s trace_id=%s stage=invoke result=SERVICE_UNAVAILABLE error=%s",
                request.session_id, invocation.trace_id, exc,
            )
            outcome = EscalateOutcome(
                message="Notre service technique est momentanement indisponible. Je transmets votre demande a notre equipe.",
                escalation_reason="SERVICE_UNAVAILABLE",
                escalation_payload=EscalationPayload(
                    category=request.service.capitalize(),
                    urgency="high",
                    context={
                        "service": request.service,
                        "problem": request.problem,
                        "entities": filtered_entities,
                        "error": str(exc),
                    },
                ),
            )
            self._record_audit(
                trace_id=trace_id, session_id=request.session_id, user_id=user_id,
                service=request.service, problem=request.problem, called_endpoint=called_endpoint,
                entities=filtered_entities, outcome=outcome, latency_ms=int((time.monotonic() - started_at) * 1000),
            )
            return outcome

        logger.info(
            "[DIAG][ENGINE] session=%s trace_id=%s stage=outcome result=%s %s",
            request.session_id, invocation.trace_id, outcome.outcome, _describe_outcome(outcome),
        )
        self._record_audit(
            trace_id=trace_id, session_id=request.session_id, user_id=user_id,
            service=request.service, problem=request.problem, called_endpoint=called_endpoint,
            entities=filtered_entities, outcome=outcome, latency_ms=int((time.monotonic() - started_at) * 1000),
        )
        return outcome
