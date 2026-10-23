"""Verifie le contrat HTTP de wallet_service (securite, manifeste, cas
generiques ne dependant d'aucune donnee precise).

Depuis que wallet_service lit en lecture seule le schema Postgres `wallet` (un
CLONE de la vraie base de ngoni-wallet-service, voir wallet_service/main.py),
il n'y a plus de mecanisme de seed pour forcer des cas precis (SUCCESS,
PENDING dans/hors SLA, KYC manquant...). Ces cas-la restent couverts par
tests/Feature/DiagnosticControllerTest.php cote PHP, la seule source de
verite sur le comportement reel de wallet-service.
"""

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wallet_service.main import app  # noqa: E402
from wallet_service.security import INTERNAL_SECRET  # noqa: E402

HEADERS = {"X-Internal-Secret": INTERNAL_SECRET}


@pytest.fixture
def client():
    return TestClient(app)


def resolve(client, user_id, reference):
    return client.post(
        "/api/v1/diagnostic/withdrawal",
        json={
            "session_id": "sess-1",
            "trace_id": "trace-1",
            "user_id": user_id,
            "problem_id": "withdrawal_pending",
            "entities": {"transaction_reference": reference},
        },
        headers=HEADERS,
    )


def resolve_topup(client, user_id, reference):
    return client.post(
        "/api/v1/diagnostic/topup",
        json={
            "session_id": "sess-1",
            "trace_id": "trace-1",
            "user_id": user_id,
            "problem_id": "topup_not_credited",
            "entities": {"transaction_reference": reference},
        },
        headers=HEADERS,
    )


def resolve_gift(client, user_id, reference):
    return client.post(
        "/api/v1/diagnostic/gift",
        json={
            "session_id": "sess-1",
            "trace_id": "trace-1",
            "user_id": user_id,
            "problem_id": "gift_not_received",
            "entities": {"gift_reference": reference},
        },
        headers=HEADERS,
    )


class TestSecurity:
    def test_manifest_requires_secret(self, client):
        response = client.get("/api/v1/diagnostic/manifest")
        assert response.status_code == 422  # header manquant

        response = client.get("/api/v1/diagnostic/manifest", headers={"X-Internal-Secret": "wrong"})
        assert response.status_code == 401

    def test_withdrawal_requires_secret(self, client):
        response = client.post(
            "/api/v1/diagnostic/withdrawal",
            json={
                "session_id": "s",
                "trace_id": "t",
                "user_id": "u",
                "problem_id": "withdrawal_pending",
                "entities": {"transaction_reference": "WITHDRAW-x"},
            },
        )
        assert response.status_code == 422

    def test_topup_requires_secret(self, client):
        response = client.post(
            "/api/v1/diagnostic/topup",
            json={
                "session_id": "s",
                "trace_id": "t",
                "user_id": "u",
                "problem_id": "topup_not_credited",
                "entities": {"transaction_reference": "TOPUP-x"},
            },
        )
        assert response.status_code == 422

    def test_gift_requires_secret(self, client):
        response = client.post(
            "/api/v1/diagnostic/gift",
            json={
                "session_id": "s",
                "trace_id": "t",
                "user_id": "u",
                "problem_id": "gift_not_received",
                "entities": {"gift_reference": "GFT-x"},
            },
        )
        assert response.status_code == 422


class TestManifest:
    def test_exposes_withdrawal_pending(self, client):
        response = client.get("/api/v1/diagnostic/manifest", headers=HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["service"] == "wallet"
        assert body["problems"][0]["id"] == "withdrawal_pending"
        assert body["problems"][0]["endpoint"]["path"] == "/diagnostic/withdrawal"
        assert body["problems"][0]["required_fields"][0]["name"] == "transaction_reference"

    def test_exposes_topup_not_credited(self, client):
        response = client.get("/api/v1/diagnostic/manifest", headers=HEADERS)

        body = response.json()
        problems = {p["id"]: p for p in body["problems"]}
        assert "topup_not_credited" in problems
        assert problems["topup_not_credited"]["endpoint"]["path"] == "/diagnostic/topup"
        assert problems["topup_not_credited"]["required_fields"][0]["name"] == "transaction_reference"

    def test_exposes_gift_not_received(self, client):
        response = client.get("/api/v1/diagnostic/manifest", headers=HEADERS)

        body = response.json()
        problems = {p["id"]: p for p in body["problems"]}
        assert "gift_not_received" in problems
        assert problems["gift_not_received"]["endpoint"]["path"] == "/diagnostic/gift"
        assert problems["gift_not_received"]["required_fields"][0]["name"] == "gift_reference"


class TestWithdrawalDiagnostic:
    def test_escalates_wallet_not_found(self, client):
        response = resolve(client, str(uuid.uuid4()), "WITHDRAW-orphan")

        body = response.json()
        assert body["outcome"] == "ESCALATE"
        assert body["escalation_reason"] == "WALLET_NOT_FOUND"

    def test_escalates_invalid_user_id(self, client):
        response = resolve(client, "not-a-uuid", "WITHDRAW-orphan")

        body = response.json()
        assert body["outcome"] == "ESCALATE"
        assert body["escalation_reason"] == "WALLET_NOT_FOUND"

    def test_missing_transaction_reference_returns_422(self, client):
        response = client.post(
            "/api/v1/diagnostic/withdrawal",
            json={
                "session_id": "s",
                "trace_id": "t",
                "user_id": str(uuid.uuid4()),
                "problem_id": "withdrawal_pending",
                "entities": {},
            },
            headers=HEADERS,
        )
        assert response.status_code == 422


class TestTopupDiagnostic:
    def test_escalates_wallet_not_found(self, client):
        response = resolve_topup(client, str(uuid.uuid4()), "TOPUP-orphan")

        body = response.json()
        assert body["outcome"] == "ESCALATE"
        assert body["escalation_reason"] == "WALLET_NOT_FOUND"

    def test_escalates_invalid_user_id(self, client):
        response = resolve_topup(client, "not-a-uuid", "TOPUP-orphan")

        body = response.json()
        assert body["outcome"] == "ESCALATE"
        assert body["escalation_reason"] == "WALLET_NOT_FOUND"

    def test_missing_transaction_reference_returns_422(self, client):
        response = client.post(
            "/api/v1/diagnostic/topup",
            json={
                "session_id": "s",
                "trace_id": "t",
                "user_id": str(uuid.uuid4()),
                "problem_id": "topup_not_credited",
                "entities": {},
            },
            headers=HEADERS,
        )
        assert response.status_code == 422


class TestGiftDiagnostic:
    def test_escalates_transaction_not_found(self, client):
        response = resolve_gift(client, str(uuid.uuid4()), "GFT-orphan")

        body = response.json()
        assert body["outcome"] == "ESCALATE"
        assert body["escalation_reason"] == "TRANSACTION_NOT_FOUND"

    def test_escalates_invalid_user_id(self, client):
        response = resolve_gift(client, "not-a-uuid", "GFT-orphan")

        body = response.json()
        assert body["outcome"] == "ESCALATE"
        assert body["escalation_reason"] == "TRANSACTION_NOT_FOUND"

    def test_missing_gift_reference_returns_422(self, client):
        response = client.post(
            "/api/v1/diagnostic/gift",
            json={
                "session_id": "s",
                "trace_id": "t",
                "user_id": str(uuid.uuid4()),
                "problem_id": "gift_not_received",
                "entities": {},
            },
            headers=HEADERS,
        )
        assert response.status_code == 422
