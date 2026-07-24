"""Preuve d'integration Adapter + CircuitBreaker (Phase 6, etape 25) : au-dela
du disjoncteur seul (test_diagnostic_circuit_breaker.py), ces tests montrent
que HttpDiagnosticAdapter.invoke() cesse reellement d'appeler le reseau une
fois le seuil d'echecs atteint -- pas seulement que le disjoncteur change
d'etat en isolation."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.diagnostic.adapter import (  # noqa: E402
    CircuitBreakerOpenError,
    DiagnosticInvocationError,
    HttpDiagnosticAdapter,
)
from app.domains.diagnostic.circuit_breaker import CircuitBreaker  # noqa: E402
from app.domains.diagnostic.contracts import (  # noqa: E402
    DiagnosticEndpoint,
    DiagnosticInvocationRequest,
    FieldSpec,
    ProblemDefinition,
)
from app.domains.diagnostic.registry import RoutableProblem  # noqa: E402


def make_target() -> RoutableProblem:
    problem = ProblemDefinition(
        id="withdrawal_pending",
        label="Retrait bloque",
        keywords=["retrait"],
        endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/withdrawal"),
        required_fields=[FieldSpec(name="transaction_reference", type="string")],
        optional_fields=[],
    )
    return RoutableProblem(
        service="wallet",
        problem=problem,
        base_url="http://wallet.test/api/v1",
        internal_secret="test-secret",
    )


def make_request() -> DiagnosticInvocationRequest:
    return DiagnosticInvocationRequest(
        session_id="sess-1",
        trace_id="trace-1",
        user_id="usr_123",
        problem_id="withdrawal_pending",
        entities={"transaction_reference": "WITHDRAW-abc123"},
    )


@pytest.mark.anyio
async def test_repeated_failures_open_the_circuit_and_stop_calling_network():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("service down", request=request)

    breaker = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=30.0)
    adapter = HttpDiagnosticAdapter(transport=httpx.MockTransport(handler), circuit_breaker=breaker)
    target = make_target()

    for _ in range(3):
        with pytest.raises(DiagnosticInvocationError):
            await adapter.invoke(target, make_request())
    assert call_count == 3

    # 4e appel : le disjoncteur est maintenant ouvert -- aucun appel reseau
    # supplementaire ne doit avoir lieu (call_count reste a 3).
    with pytest.raises(CircuitBreakerOpenError):
        await adapter.invoke(target, make_request())
    assert call_count == 3


@pytest.mark.anyio
async def test_success_after_failures_keeps_circuit_closed_for_next_calls():
    responses = iter([
        httpx.Response(500),
        httpx.Response(
            200,
            json={
                "outcome": "RESOLVED",
                "message": "Retrait effectue.",
                "resolution_code": "WITHDRAWAL_COMPLETED",
                "data": {},
            },
        ),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    breaker = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=30.0)
    adapter = HttpDiagnosticAdapter(transport=httpx.MockTransport(handler), circuit_breaker=breaker)
    target = make_target()

    with pytest.raises(DiagnosticInvocationError):
        await adapter.invoke(target, make_request())

    outcome = await adapter.invoke(target, make_request())
    assert outcome.outcome == "RESOLVED"

    # Le succes a reinitialise le compteur d'echecs -- le disjoncteur reste ferme.
    assert breaker.is_open("http://wallet.test/api/v1") is False


@pytest.mark.anyio
async def test_invalid_response_does_not_count_as_a_circuit_failure():
    """Une reponse HTTP 200 mais non conforme au contrat n'est pas une panne
    reseau -- ne doit jamais ouvrir le disjoncteur (voir adapter.py)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"outcome": "NOT_A_REAL_OUTCOME"})

    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=30.0)
    adapter = HttpDiagnosticAdapter(transport=httpx.MockTransport(handler), circuit_breaker=breaker)
    target = make_target()

    with pytest.raises(DiagnosticInvocationError):
        await adapter.invoke(target, make_request())

    assert breaker.is_open("http://wallet.test/api/v1") is False


@pytest.fixture
def anyio_backend():
    return "asyncio"
