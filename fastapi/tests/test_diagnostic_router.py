"""Tests HTTP de la route POST /diagnostic/resolve, isoles du reste de
l'application (pas de DB, pas de Rasa) : seul le routeur de diagnostic est
monte, et le DiagnosticPipeline est remplace par un double de test via
app.dependency_overrides. Ces tests verifient le contrat HTTP du endpoint
(header obligatoire, code 404 si probleme inconnu, relai fidele de la sortie
du pipeline) -- la logique du pipeline lui-meme est testee dans
test_diagnostic_pipeline.py.
"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.diagnostic.contracts import ResolvedOutcome  # noqa: E402
from app.domains.diagnostic.pipeline import UnknownProblem  # noqa: E402
from app.domains.diagnostic.router import get_pipeline, router  # noqa: E402


class FakePipeline:
    def __init__(self, outcome=None, exception=None):
        self._outcome = outcome
        self._exception = exception
        self.calls = []

    async def resolve(self, user_id, request):
        self.calls.append((user_id, request))
        if self._exception is not None:
            raise self._exception
        return self._outcome


def make_client(fake_pipeline: FakePipeline) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_pipeline] = lambda: fake_pipeline
    return TestClient(app)


VALID_BODY = {
    "session_id": "sess-1",
    "service": "wallet",
    "problem": "withdrawal_pending",
    "entities": {"transaction_reference": "WITHDRAW-abc123"},
}


def test_resolve_requires_x_user_id_header():
    client = make_client(FakePipeline(outcome=None))

    response = client.post("/diagnostic/resolve", json=VALID_BODY)

    assert response.status_code == 422


def test_resolve_returns_pipeline_outcome_as_is():
    outcome = ResolvedOutcome(
        message="Votre retrait a bien ete effectue.",
        resolution_code="WITHDRAWAL_COMPLETED",
    )
    fake_pipeline = FakePipeline(outcome=outcome)
    client = make_client(fake_pipeline)

    response = client.post(
        "/diagnostic/resolve", json=VALID_BODY, headers={"X-User-ID": "usr_123"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "RESOLVED"
    assert body["resolution_code"] == "WITHDRAWAL_COMPLETED"

    user_id, request = fake_pipeline.calls[0]
    assert user_id == "usr_123"
    assert request.service == "wallet"
    assert request.problem == "withdrawal_pending"


def test_resolve_returns_404_for_unknown_problem():
    fake_pipeline = FakePipeline(exception=UnknownProblem("wallet", "unknown_problem"))
    client = make_client(fake_pipeline)

    response = client.post(
        "/diagnostic/resolve",
        json={**VALID_BODY, "problem": "unknown_problem"},
        headers={"X-User-ID": "usr_123"},
    )

    assert response.status_code == 404
