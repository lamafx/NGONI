"""Phase 6, etape 27 (voir docs/diagnostic-roadmap.md) : contrairement a
test_diagnostic_contracts.py (qui valide des FIXTURES statiques dans
contracts/diagnostic/v1/examples/), ces tests valident les REPONSES REELLES
servies par wallet_service et user_service -- round-trip complet (objet Python ->
serialisation JSON -> HTTP -> parsing -> validation Pydantic), pour detecter
toute divergence entre un manifeste/une reponse reellement en production et
le contrat qu'il est cense respecter. Sans ces tests, un champ mal type
ajoute a un manifest.py ne serait detecte qu'au premier appel reel du
Diagnostic Engine (voir CapabilityManifest.model_validate dans registry.py),
pas en CI."""

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.diagnostic.contracts import (  # noqa: E402
    CapabilityManifest,
    DiagnosticInvocationResponseAdapter,
)
from user_service.main import app as user_app  # noqa: E402
from user_service.security import INTERNAL_SECRET as USER_SECRET  # noqa: E402
from wallet_service.main import app as wallet_app  # noqa: E402
from wallet_service.security import INTERNAL_SECRET as WALLET_SECRET  # noqa: E402


@pytest.fixture
def wallet_client():
    return TestClient(wallet_app)


@pytest.fixture
def user_client():
    return TestClient(user_app)


class TestRealManifestsConformToContract:
    def test_wallet_manifest_is_a_valid_capability_manifest(self, wallet_client):
        response = wallet_client.get(
            "/api/v1/diagnostic/manifest", headers={"X-Internal-Secret": WALLET_SECRET}
        )
        assert response.status_code == 200

        # Leve ValidationError (donc echoue le test) si le manifeste
        # REELLEMENT servi par wallet_service ne respecte plus le contrat --
        # pas seulement un exemple fige dans examples/valid/.
        manifest = CapabilityManifest.model_validate(response.json())
        assert manifest.service == "wallet"
        assert len(manifest.problems) == 8

    def test_user_manifest_is_a_valid_capability_manifest(self, user_client):
        response = user_client.get(
            "/api/v1/diagnostic/manifest", headers={"X-Internal-Secret": USER_SECRET}
        )
        assert response.status_code == 200

        manifest = CapabilityManifest.model_validate(response.json())
        assert manifest.service == "user"
        assert len(manifest.problems) == 12


class TestRealResponsesConformToEnvelope:
    """Un utilisateur inconnu (UUID aleatoire, jamais dans la base) donne un
    resultat deterministe pour chaque probleme -- pas besoin de seed, meme
    principe que tests/test_wallet_service.py."""

    @pytest.mark.parametrize(
        "path, problem_id, entity_key",
        [
            ("/api/v1/diagnostic/withdrawal", "withdrawal_pending", "transaction_reference"),
            ("/api/v1/diagnostic/topup", "topup_not_credited", "transaction_reference"),
            ("/api/v1/diagnostic/gift", "gift_not_received", "gift_reference"),
        ],
    )
    def test_wallet_response_conforms_to_envelope(self, wallet_client, path, problem_id, entity_key):
        response = wallet_client.post(
            path,
            json={
                "session_id": "s", "trace_id": "t", "user_id": str(uuid.uuid4()),
                "problem_id": problem_id, "entities": {entity_key: "REF-orphan"},
            },
            headers={"X-Internal-Secret": WALLET_SECRET},
        )
        assert response.status_code == 200

        # Type discrimine (RESOLVED | ESCALATE | NEED_MORE_INFO) : leve si le
        # champ "outcome" ou la forme du JSON ne correspond a aucune des 3.
        outcome = DiagnosticInvocationResponseAdapter.validate_python(response.json())
        assert outcome.outcome == "ESCALATE"

    @pytest.mark.parametrize(
        "path, problem_id",
        [
            ("/api/v1/diagnostic/kyc_status", "kyc_status_issue"),
            ("/api/v1/diagnostic/account_status", "account_access_blocked"),
            ("/api/v1/diagnostic/compliance_hold", "compliance_hold_blocking"),
            ("/api/v1/diagnostic/account_deletion", "account_deletion_status"),
            ("/api/v1/diagnostic/parental_consent", "parental_consent_status"),
        ],
    )
    def test_user_response_conforms_to_envelope(self, user_client, path, problem_id):
        response = user_client.post(
            path,
            json={
                "session_id": "s", "trace_id": "t", "user_id": str(uuid.uuid4()),
                "problem_id": problem_id, "entities": {},
            },
            headers={"X-Internal-Secret": USER_SECRET},
        )
        assert response.status_code == 200

        # Deterministe mais pas forcement ESCALATE ici (account_deletion_status
        # et parental_consent_status resolvent "aucune ligne trouvee" en
        # RESOLVED, pas en ESCALATE -- voir leurs service_*.py respectifs) :
        # le test verifie la CONFORMITE au contrat, pas un outcome precis.
        DiagnosticInvocationResponseAdapter.validate_python(response.json())
