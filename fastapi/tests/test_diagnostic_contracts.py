"""Tests de conformite entre les fixtures de contracts/diagnostic/v1/examples/
et leur miroir Pydantic (app.domains.diagnostic.contracts).

Objectif : detecter toute divergence entre les fichiers .schema.json (source
de verite, langage-agnostique) et l'implementation Python du Diagnostic
Engine, sans dependre d'une librairie de validation JSON Schema externe.

Ces tests n'importent volontairement pas app.main / app.database : le module
app.domains.diagnostic.contracts ne depend que de pydantic.
"""

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.diagnostic.contracts import (  # noqa: E402
    CapabilityManifest,
    DiagnosticInvocationRequest,
    DiagnosticInvocationResponseAdapter,
    DiagnosticResolveRequest,
)

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "diagnostic" / "v1"
VALID_DIR = CONTRACTS_DIR / "examples" / "valid"
INVALID_DIR = CONTRACTS_DIR / "examples" / "invalid"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_contracts_directory_exists():
    assert CONTRACTS_DIR.is_dir(), (
        "contracts/diagnostic/v1 introuvable : ce test doit tourner depuis un "
        "checkout complet du depot, pas uniquement du dossier fastapi/."
    )


class TestValidFixtures:
    def test_client_request(self):
        payload = load(VALID_DIR / "client-request.withdrawal_pending.json")
        model = DiagnosticResolveRequest.model_validate(payload)
        assert model.service == "wallet"
        assert model.problem == "withdrawal_pending"
        assert model.entities["transaction_reference"] == "WITHDRAW-abc123"

    def test_service_invocation_request(self):
        payload = load(VALID_DIR / "service-invocation-request.withdrawal_pending.json")
        model = DiagnosticInvocationRequest.model_validate(payload)
        assert model.problem_id == "withdrawal_pending"
        assert model.user_id == "usr_123"

    def test_response_resolved(self):
        payload = load(VALID_DIR / "service-invocation-response.resolved.json")
        model = DiagnosticInvocationResponseAdapter.validate_python(payload)
        assert model.outcome == "RESOLVED"
        assert model.resolution_code == "TOPUP_SETTLED_ON_DEMAND"

    def test_response_escalate(self):
        payload = load(VALID_DIR / "service-invocation-response.escalate.json")
        model = DiagnosticInvocationResponseAdapter.validate_python(payload)
        assert model.outcome == "ESCALATE"
        assert model.escalation_payload.category == "Wallet"
        assert model.escalation_payload.urgency == "high"

    def test_response_need_more_info(self):
        payload = load(VALID_DIR / "service-invocation-response.need_more_info.json")
        model = DiagnosticInvocationResponseAdapter.validate_python(payload)
        assert model.outcome == "NEED_MORE_INFO"
        assert model.missing_fields == ["transaction_reference"]

    def test_capability_manifest(self):
        payload = load(VALID_DIR / "capability-manifest.wallet.json")
        model = CapabilityManifest.model_validate(payload)
        assert model.service == "wallet"
        assert {p.id for p in model.problems} == {
            "withdrawal_pending",
            "topup_not_credited",
            "gift_not_received",
        }


INVALID_CASES = [
    ("service-invocation-response.missing_message.json", "response"),
    ("service-invocation-response.unknown_outcome.json", "response"),
    ("client-request.bad_problem_id.json", "client_request"),
    ("capability-manifest.missing_endpoint.json", "manifest"),
]


@pytest.mark.parametrize("filename, kind", INVALID_CASES)
def test_invalid_fixtures_are_rejected(filename, kind):
    payload = load(INVALID_DIR / filename)

    with pytest.raises(ValidationError):
        if kind == "response":
            DiagnosticInvocationResponseAdapter.validate_python(payload)
        elif kind == "client_request":
            DiagnosticResolveRequest.model_validate(payload)
        elif kind == "manifest":
            CapabilityManifest.model_validate(payload)
        else:  # pragma: no cover - garde-fou si INVALID_CASES est etendu sans mise a jour
            raise AssertionError(f"kind inconnu: {kind}")
