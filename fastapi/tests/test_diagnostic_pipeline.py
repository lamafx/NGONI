"""Tests du Diagnostic Engine (Phase 1) sans wallet-service reel.

Le vrai wallet-service (PHP/Postgres/Docker) n'est pas disponible dans cet
environnement de test : ces tests simulent son comportement HTTP via
httpx.MockTransport, en respectant exactement les contrats de
contracts/diagnostic/v1/ verifies par test_diagnostic_contracts.py. Ils
prouvent que le Registry, l'Adapter et le Pipeline fonctionnent correctement
independamment de toute infrastructure externe.

Le test end-to-end contre le vrai wallet-service (docker-compose complet)
est documente separement -- voir docs/diagnostic-roadmap.md, Phase 1, etape 10.
"""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.diagnostic.adapter import HttpDiagnosticAdapter  # noqa: E402
from app.domains.diagnostic.contracts import DiagnosticResolveRequest  # noqa: E402
from app.domains.diagnostic.pipeline import DiagnosticPipeline, UnknownProblem  # noqa: E402
from app.domains.diagnostic.registry import CapabilityRegistry, RegisteredService  # noqa: E402

WALLET_MANIFEST = {
    "service": "wallet",
    "manifest_version": "1.0.0",
    "base_url": "http://wallet-service.test/api/v1",
    "protocol": "REST",
    "problems": [
        {
            "id": "withdrawal_pending",
            "label": "Retrait bloque ou en attente",
            "keywords": ["retrait"],
            "endpoint": {"method": "POST", "path": "/diagnostic/withdrawal"},
            "required_fields": [
                {"name": "transaction_reference", "type": "string"},
            ],
            "optional_fields": [
                {"name": "amount", "type": "number"},
            ],
        },
    ],
}


def wallet_service() -> RegisteredService:
    return RegisteredService(
        name="wallet",
        base_url="http://wallet-service.test/api/v1",
        internal_secret="test-secret",
    )


def make_registry(handler) -> CapabilityRegistry:
    transport = httpx.MockTransport(handler)
    return CapabilityRegistry(services=[wallet_service()], transport=transport)


def make_pipeline(registry: CapabilityRegistry, handler) -> DiagnosticPipeline:
    transport = httpx.MockTransport(handler)
    return DiagnosticPipeline(registry, adapter=HttpDiagnosticAdapter(transport=transport))


class TestCapabilityRegistry:
    @pytest.mark.anyio
    async def test_refresh_indexes_problems_from_real_manifest_shape(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/diagnostic/manifest"
            assert request.headers["X-Internal-Secret"] == "test-secret"
            return httpx.Response(200, json=WALLET_MANIFEST)

        registry = make_registry(handler)
        assert registry.is_empty()

        await registry.refresh()

        target = registry.lookup("wallet", "withdrawal_pending")
        assert target is not None
        assert target.base_url == "http://wallet-service.test/api/v1"
        assert target.problem.endpoint.path == "/diagnostic/withdrawal"
        assert {f.name for f in target.problem.required_fields} == {"transaction_reference"}

    @pytest.mark.anyio
    async def test_unreachable_service_is_ignored_not_fatal(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("service down", request=request)

        registry = make_registry(handler)
        await registry.refresh()

        assert registry.is_empty()
        assert registry.lookup("wallet", "withdrawal_pending") is None


class TestDiagnosticPipeline:
    @pytest.mark.anyio
    async def test_missing_required_field_returns_need_more_info_without_calling_service(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path.endswith("/diagnostic/manifest"):
                return httpx.Response(200, json=WALLET_MANIFEST)
            raise AssertionError("le pipeline n'aurait jamais du appeler /diagnostic/withdrawal ici")

        registry = make_registry(handler)
        pipeline = make_pipeline(registry, handler)

        request = DiagnosticResolveRequest(
            session_id="sess-1", service="wallet", problem="withdrawal_pending", entities={}
        )
        outcome = await pipeline.resolve("usr_123", request)

        assert outcome.outcome == "NEED_MORE_INFO"
        assert outcome.missing_fields == ["transaction_reference"]
        assert "/api/v1/diagnostic/withdrawal" not in calls

    @pytest.mark.anyio
    async def test_complete_request_is_routed_and_response_normalized(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/diagnostic/manifest"):
                return httpx.Response(200, json=WALLET_MANIFEST)

            assert request.url.path.endswith("/diagnostic/withdrawal")
            import json as _json

            payload = _json.loads(request.content)
            assert payload["problem_id"] == "withdrawal_pending"
            assert payload["user_id"] == "usr_123"
            assert payload["entities"] == {"transaction_reference": "WITHDRAW-abc123"}

            return httpx.Response(
                200,
                json={
                    "outcome": "RESOLVED",
                    "message": "Votre retrait a bien ete effectue.",
                    "resolution_code": "WITHDRAWAL_COMPLETED",
                    "data": {},
                },
            )

        registry = make_registry(handler)
        pipeline = make_pipeline(registry, handler)

        request = DiagnosticResolveRequest(
            session_id="sess-1",
            service="wallet",
            problem="withdrawal_pending",
            entities={"transaction_reference": "WITHDRAW-abc123"},
        )
        outcome = await pipeline.resolve("usr_123", request)

        assert outcome.outcome == "RESOLVED"
        assert outcome.resolution_code == "WITHDRAWAL_COMPLETED"

    @pytest.mark.anyio
    async def test_downstream_failure_triggers_automatic_escalation(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/diagnostic/manifest"):
                return httpx.Response(200, json=WALLET_MANIFEST)
            raise httpx.ConnectError("wallet-service down", request=request)

        registry = make_registry(handler)
        pipeline = make_pipeline(registry, handler)

        request = DiagnosticResolveRequest(
            session_id="sess-1",
            service="wallet",
            problem="withdrawal_pending",
            entities={"transaction_reference": "WITHDRAW-abc123"},
        )
        outcome = await pipeline.resolve("usr_123", request)

        assert outcome.outcome == "ESCALATE"
        assert outcome.escalation_reason == "SERVICE_UNAVAILABLE"
        assert outcome.escalation_payload.category == "Wallet"

    @pytest.mark.anyio
    async def test_unknown_problem_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=WALLET_MANIFEST)

        registry = make_registry(handler)
        pipeline = make_pipeline(registry, handler)

        request = DiagnosticResolveRequest(
            session_id="sess-1", service="wallet", problem="gift_not_received", entities={}
        )

        with pytest.raises(UnknownProblem):
            await pipeline.resolve("usr_123", request)


@pytest.fixture
def anyio_backend():
    return "asyncio"
