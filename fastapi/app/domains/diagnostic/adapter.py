"""Adapter HTTP generique pour invoquer un microservice de diagnostic.

Un seul Adapter existe pour la Phase 1 (protocole REST -- le seul declare par
le manifeste wallet). Une Phase ulterieure pourra selectionner l'Adapter par
un Factory keye sur le champ `protocol` du manifeste (voir
contracts/diagnostic/README.md et docs/diagnostic-flow.md, table des Design
Patterns) sans modifier ni le Registry ni le Pipeline.

Phase 6 (etape 25, voir docs/diagnostic-roadmap.md) : timeout configurable +
disjoncteur PAR microservice (voir circuit_breaker.py). Une instance
d'Adapter est partagee entre toutes les requetes (voir router.py,
get_pipeline) : le disjoncteur doit donc etre partage lui aussi pour que ses
compteurs d'echecs consecutifs aient un sens a travers les requetes -- un
disjoncteur recree a chaque appel ne "disjoncterait" jamais.
"""

from __future__ import annotations

import logging
import os
import time

import httpx
from pydantic import ValidationError

from .circuit_breaker import CircuitBreaker
from .contracts import (
    DiagnosticInvocationRequest,
    DiagnosticInvocationResponse,
    DiagnosticInvocationResponseAdapter,
)
from .registry import RoutableProblem

logger = logging.getLogger(__name__)

# Timeout par appel HTTP vers un microservice -- au-dela, httpx leve
# ReadTimeout, traite ci-dessous comme n'importe quel autre echec reseau
# (DiagnosticInvocationError -> escalade automatique, voir pipeline.py).
DIAGNOSTIC_CALL_TIMEOUT_SECONDS = float(os.getenv("DIAGNOSTIC_CALL_TIMEOUT_SECONDS", "10.0"))

# Nombre d'echecs consecutifs avant ouverture du disjoncteur pour un service
# donne, et duree pendant laquelle il reste ouvert avant un nouvel essai
# (etat semi-ouvert, voir CircuitBreaker). 3 echecs "vrais" (apres timeout ou
# erreur HTTP, pas juste une reponse non conforme isolee) est un seuil bas
# deliberement : mieux vaut escalader vite un service reellement en panne que
# faire attendre plusieurs utilisateurs le meme timeout complet chacun.
CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3"))
CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS = float(os.getenv("CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS", "30.0"))


class DiagnosticInvocationError(RuntimeError):
    """Le microservice invoque est injoignable, en disjoncteur ouvert, ou
    renvoie une reponse non conforme a
    contracts/diagnostic/v1/service-invocation-response.schema.json."""


class CircuitBreakerOpenError(DiagnosticInvocationError):
    """Cas particulier de DiagnosticInvocationError : aucun appel reseau n'a
    ete tente, le disjoncteur etait deja ouvert pour ce service (voir
    CircuitBreaker.is_open). Distingue ce cas d'un vrai echec HTTP dans les
    logs/l'audit -- utile pour comprendre une salve d'escalades sans y voir
    une salve de pannes reseau independantes."""


class HttpDiagnosticAdapter:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._transport = transport
        # Une instance par defaut si aucune n'est fournie : suffisant pour
        # les tests (chaque test cree son propre Adapter, donc son propre
        # disjoncteur, jamais partage entre tests). En production, router.py
        # construit un SEUL Adapter partage (voir docstring du module) pour
        # que le disjoncteur ait un etat coherent entre requetes.
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            reset_timeout_seconds=CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS,
        )

    async def invoke(
        self,
        target: RoutableProblem,
        request: DiagnosticInvocationRequest,
    ) -> DiagnosticInvocationResponse:
        url = f"{target.base_url}{target.problem.endpoint.path}"
        breaker_key = target.base_url

        if self._circuit_breaker.is_open(breaker_key):
            logger.warning(
                "[DIAG][ADAPTER] trace_id=%s stage=circuit_breaker result=OPEN service=%s -- appel non tente",
                request.trace_id, breaker_key,
            )
            raise CircuitBreakerOpenError(
                f"Disjoncteur ouvert pour {breaker_key} (trop d'echecs consecutifs recents) : appel non tente"
            )

        headers = {
            "X-Internal-Secret": target.internal_secret,
            "X-Request-ID": request.trace_id,
        }

        logger.info(
            "[DIAG][ADAPTER] trace_id=%s stage=http_call method=POST url=%s",
            request.trace_id, url,
        )

        started_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=DIAGNOSTIC_CALL_TIMEOUT_SECONDS, transport=self._transport) as client:
                response = await client.post(url, json=request.model_dump(), headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            self._circuit_breaker.record_failure(breaker_key)
            logger.warning(
                "[DIAG][ADAPTER] trace_id=%s stage=http_call result=ERROR error=%s duration_ms=%d",
                request.trace_id, exc, (time.monotonic() - started_at) * 1000,
            )
            raise DiagnosticInvocationError(f"Appel a {url} impossible: {exc}") from exc

        logger.info(
            "[DIAG][ADAPTER] trace_id=%s stage=http_call result=OK status=%s duration_ms=%d",
            request.trace_id, response.status_code, (time.monotonic() - started_at) * 1000,
        )

        try:
            outcome = DiagnosticInvocationResponseAdapter.validate_python(response.json())
        except ValidationError as exc:
            # Une reponse HTTP 200 mais non conforme est un signe que le
            # service repond, juste incorrectement -- pas une panne reseau.
            # On NE compte PAS ça comme un echec du disjoncteur : ouvrir le
            # circuit sur un bug de contrat empecherait aussi les AUTRES
            # problemes (potentiellement corrects) de ce meme service d'etre
            # appeles, pour une cause qui leur est etrangere.
            logger.warning(
                "[DIAG][ADAPTER] trace_id=%s stage=http_call result=INVALID_RESPONSE error=%s",
                request.trace_id, exc,
            )
            raise DiagnosticInvocationError(
                f"Reponse de {url} non conforme au contrat service-invocation-response: {exc}"
            ) from exc

        self._circuit_breaker.record_success(breaker_key)
        return outcome
