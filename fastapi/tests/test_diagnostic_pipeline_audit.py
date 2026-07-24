"""Preuve que DiagnosticPipeline appelle reellement le DiagnosticAuditRepository
aux bons moments (Phase 6, etape 26) -- au-dela de test_diagnostic_audit_repository.py
(qui teste le repository seul) et test_diagnostic_pipeline.py (qui ne verifie
pas la tracabilite, audit_repository=None par defaut)."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.diagnostic.contracts import DiagnosticResolveRequest  # noqa: E402
from app.domains.diagnostic.pipeline import DiagnosticPipeline  # noqa: E402
from app.domains.diagnostic.registry import CapabilityRegistry, RegisteredService  # noqa: E402

WALLET_MANIFEST = {
    "service": "wallet",
    "manifest_version": "1.0.0",
    "base_url": "http://wallet.test/api/v1",
    "protocol": "REST",
    "problems": [
        {
            "id": "withdrawal_pending",
            "label": "Retrait bloque",
            "keywords": ["retrait"],
            "endpoint": {"method": "POST", "path": "/diagnostic/withdrawal"},
            "required_fields": [{"name": "transaction_reference", "type": "string"}],
            "optional_fields": [],
        },
    ],
}


class FakeAuditRepository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, **kwargs) -> None:
        self.calls.append(kwargs)


def make_registry(handler) -> CapabilityRegistry:
    service = RegisteredService(name="wallet", base_url="http://wallet.test/api/v1", internal_secret="s")
    return CapabilityRegistry(services=[service], transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_resolved_outcome_is_recorded():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/diagnostic/manifest"):
            return httpx.Response(200, json=WALLET_MANIFEST)
        return httpx.Response(
            200,
            json={"outcome": "RESOLVED", "message": "ok", "resolution_code": "WITHDRAWAL_COMPLETED", "data": {}},
        )

    audit = FakeAuditRepository()
    from app.domains.diagnostic.adapter import HttpDiagnosticAdapter

    pipeline = DiagnosticPipeline(
        make_registry(handler), adapter=HttpDiagnosticAdapter(transport=httpx.MockTransport(handler)),
        audit_repository=audit,
    )
    request = DiagnosticResolveRequest(
        session_id="sess-1", service="wallet", problem="withdrawal_pending",
        entities={"transaction_reference": "WITHDRAW-abc"},
    )

    await pipeline.resolve("usr_123", request)

    assert len(audit.calls) == 1
    call = audit.calls[0]
    assert call["session_id"] == "sess-1"
    assert call["outcome"] == "RESOLVED"
    assert call["outcome_detail"] == "WITHDRAWAL_COMPLETED"
    assert call["called_endpoint"] == "http://wallet.test/api/v1/diagnostic/withdrawal"
    assert call["latency_ms"] is not None


@pytest.mark.anyio
async def test_need_more_info_is_recorded_without_calling_service():
    calls_to_service = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/diagnostic/manifest"):
            return httpx.Response(200, json=WALLET_MANIFEST)
        calls_to_service.append(request.url.path)
        raise AssertionError("ne doit jamais appeler le microservice si des champs manquent")

    audit = FakeAuditRepository()
    from app.domains.diagnostic.adapter import HttpDiagnosticAdapter

    pipeline = DiagnosticPipeline(
        make_registry(handler), adapter=HttpDiagnosticAdapter(transport=httpx.MockTransport(handler)),
        audit_repository=audit,
    )
    request = DiagnosticResolveRequest(session_id="sess-1", service="wallet", problem="withdrawal_pending", entities={})

    await pipeline.resolve("usr_123", request)

    assert calls_to_service == []
    assert len(audit.calls) == 1
    assert audit.calls[0]["outcome"] == "NEED_MORE_INFO"
    assert audit.calls[0]["called_endpoint"] is None


@pytest.mark.anyio
async def test_service_unavailable_escalation_is_recorded():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/diagnostic/manifest"):
            return httpx.Response(200, json=WALLET_MANIFEST)
        raise httpx.ConnectError("down", request=request)

    audit = FakeAuditRepository()
    from app.domains.diagnostic.adapter import HttpDiagnosticAdapter

    pipeline = DiagnosticPipeline(
        make_registry(handler), adapter=HttpDiagnosticAdapter(transport=httpx.MockTransport(handler)),
        audit_repository=audit,
    )
    request = DiagnosticResolveRequest(
        session_id="sess-1", service="wallet", problem="withdrawal_pending",
        entities={"transaction_reference": "WITHDRAW-abc"},
    )

    await pipeline.resolve("usr_123", request)

    assert len(audit.calls) == 1
    assert audit.calls[0]["outcome"] == "ESCALATE"
    assert audit.calls[0]["outcome_detail"] == "SERVICE_UNAVAILABLE"


@pytest.mark.anyio
async def test_audit_repository_failure_never_breaks_the_response():
    class BrokenAuditRepository:
        def record(self, **kwargs):
            raise RuntimeError("DB indisponible")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/diagnostic/manifest"):
            return httpx.Response(200, json=WALLET_MANIFEST)
        return httpx.Response(
            200,
            json={"outcome": "RESOLVED", "message": "ok", "resolution_code": "WITHDRAWAL_COMPLETED", "data": {}},
        )

    from app.domains.diagnostic.adapter import HttpDiagnosticAdapter

    pipeline = DiagnosticPipeline(
        make_registry(handler), adapter=HttpDiagnosticAdapter(transport=httpx.MockTransport(handler)),
        audit_repository=BrokenAuditRepository(),
    )
    request = DiagnosticResolveRequest(
        session_id="sess-1", service="wallet", problem="withdrawal_pending",
        entities={"transaction_reference": "WITHDRAW-abc"},
    )

    outcome = await pipeline.resolve("usr_123", request)

    assert outcome.outcome == "RESOLVED"


@pytest.fixture
def anyio_backend():
    return "asyncio"
