import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client():
    with patch("sqlalchemy.create_engine"):
        sys.modules.pop("app.database", None)
        sys.modules.pop("app.main", None)
        import app.database  # noqa: F401
        import app.main as main_module

        def fake_get_db():
            class FakeSession:
                def execute(self, *args, **kwargs):
                    return None

                def add(self, *args, **kwargs):
                    return None

                def refresh(self, *args, **kwargs):
                    return None

                def commit(self):
                    return None

                def rollback(self):
                    return None

                def close(self):
                    return None

            yield FakeSession()

        main_module.app.dependency_overrides[main_module.get_db] = fake_get_db
        with TestClient(main_module.app) as test_client:
            yield test_client
        main_module.app.dependency_overrides.clear()


def test_create_ticket_endpoint_returns_ticket_payload(client):
    response = client.post(
        "/tickets/create",
        json={
            "category": "KYC",
            "description": "Mon KYC est bloqué",
            "urgency": "high",
            "incident_date": "2026-06-29",
            "summary": "Résumé automatique",
            "confirmation": "oui",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "OPEN"
    assert payload["message"] == "Ticket créé avec succès"
    assert payload["ticket_id"].startswith("CMP-")
