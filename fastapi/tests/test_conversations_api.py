"""Surface HTTP de la prise en charge humaine, bout en bout.

Complete test_conversations_handoff.py (qui teste les regles metier en
appelant le service directement) : ici on passe par les VRAIES routes, avec
les en-tetes reels -- c'est ce qui verifie que l'espace conseiller est bien
ferme sans le secret partage, et que le parcours complet tient depuis le
client jusqu'au poste du conseiller.

Ignore (skip) si aucune base n'est joignable, comme l'autre fichier.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ADMIN_SECRET = "test-suite-admin-secret"
# Defini AVANT l'import de app.shared.admin_auth (qui lit la variable au
# chargement du module) -- sans ca, toutes les routes admin refuseraient.
os.environ["ADMIN_INTERNAL_SECRET"] = ADMIN_SECRET

from app.database import SessionLocal  # noqa: E402
from app.domains.conversations.models import Conversation, ConversationMessage  # noqa: E402
from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Internal-Secret": ADMIN_SECRET, "X-User-ID": "test-admin"}


@pytest.fixture
def client():
    # Sans gestionnaire de contexte : les evenements de demarrage (chargement
    # du modele d'embeddings, attente de Rasa) ne sont pas joues -- ce test ne
    # touche ni l'un ni l'autre et n'a pas a payer une minute de chargement.
    return TestClient(app)


@pytest.fixture
def conversation_id():
    try:
        db = SessionLocal()
        db.execute(Conversation.__table__.select().limit(1))
    except Exception as error:  # pragma: no cover - depend de l'environnement
        pytest.skip(f"PostgreSQL indisponible : {error}")
    generated = f"test-api-{uuid.uuid4().hex[:12]}"
    yield generated
    db.query(ConversationMessage).filter(
        ConversationMessage.conversation_id == generated
    ).delete()
    db.query(Conversation).filter(Conversation.conversation_id == generated).delete()
    db.commit()
    db.close()


def test_admin_routes_are_closed_without_the_shared_secret(client):
    for method, path in [
        ("get", "/admin/conversations/"),
        ("get", "/admin/agents/"),
        ("get", "/admin/dashboard/summary"),
        ("get", "/admin/users/"),
        ("get", "/admin/system/health"),
        ("get", "/admin/diagnostics/runs"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code in (401, 422), f"{path} n'est pas protégée"


def test_client_to_agent_round_trip(client, conversation_id):
    # 1. Le client journalise un tour (il parle a Rasa directement, voir
    #    TurnRequest) : la conversation nait ici.
    turn = client.post(
        "/conversations/turns",
        json={
            "conversation_id": conversation_id,
            "user_text": "mon retrait est bloqué depuis hier",
            "intent": "diagnostic",
            "confidence": 0.93,
            "bot_messages": [{"text": "Je vérifie votre retrait."}],
        },
    )
    assert turn.status_code == 201
    assert turn.json()["handoff"] is False

    # 2. Le client demande un conseiller.
    escalated = client.post(
        "/conversations/escalate",
        json={"conversation_id": conversation_id, "reason": "demande_utilisateur"},
    )
    assert escalated.status_code == 200
    assert escalated.json()["status"] == "ESCALADE_DEMANDEE"
    # L'assistant n'est pas encore coupe : personne n'a repris la main.
    assert escalated.json()["handoff"] is False

    # 3. Le conseiller voit la conversation dans sa file, avec son contexte.
    queue = client.get("/admin/conversations/?escalated=true", headers=ADMIN_HEADERS)
    assert queue.status_code == 200
    assert any(row["conversation_id"] == conversation_id for row in queue.json())

    context = client.get(f"/admin/conversations/{conversation_id}/context", headers=ADMIN_HEADERS)
    assert context.status_code == 200
    assert context.json()["intents_seen"] == ["diagnostic"]

    # 4. Prise en charge : le bot se tait.
    assigned = client.post(
        f"/admin/conversations/{conversation_id}/assign",
        json={"agent_id": "conseiller-test"},
        headers=ADMIN_HEADERS,
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "PRISE_EN_CHARGE"

    turn_during_handoff = client.post(
        "/conversations/turns",
        json={"conversation_id": conversation_id, "user_text": "vous êtes là ?"},
    )
    assert turn_during_handoff.json()["handoff"] is True
    assert turn_during_handoff.json()["assigned_to"] == "conseiller-test"

    # 5. Reponse humaine, recuperee par le client.
    reply = client.post(
        f"/admin/conversations/{conversation_id}/messages",
        json={"text": "Bonjour, je reprends votre dossier.", "agent_id": "conseiller-test"},
        headers=ADMIN_HEADERS,
    )
    assert reply.status_code == 201

    updates = client.get(f"/conversations/{conversation_id}/updates")
    assert updates.status_code == 200
    body = updates.json()
    assert body["handoff"] is True
    assert any(message["sender_role"] == "agent" for message in body["messages"])

    # 6. Cloture.
    resolved = client.post(
        f"/admin/conversations/{conversation_id}/resolve",
        json={"agent_id": "conseiller-test"},
        headers=ADMIN_HEADERS,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLUE"


def test_a_second_advisor_cannot_silently_take_over(client, conversation_id):
    client.post(
        "/conversations/turns",
        json={"conversation_id": conversation_id, "user_text": "bonjour", "intent": "greet"},
    )
    client.post(
        f"/admin/conversations/{conversation_id}/assign",
        json={"agent_id": "conseiller-a"},
        headers=ADMIN_HEADERS,
    )
    conflict = client.post(
        f"/admin/conversations/{conversation_id}/assign",
        json={"agent_id": "conseiller-b"},
        headers=ADMIN_HEADERS,
    )
    assert conflict.status_code == 409

    forced = client.post(
        f"/admin/conversations/{conversation_id}/assign?force=true",
        json={"agent_id": "conseiller-b"},
        headers=ADMIN_HEADERS,
    )
    assert forced.status_code == 200
    assert forced.json()["assigned_to"] == "conseiller-b"


def test_an_advisor_cannot_write_before_taking_the_conversation(client, conversation_id):
    client.post(
        "/conversations/turns",
        json={"conversation_id": conversation_id, "user_text": "bonjour", "intent": "greet"},
    )
    refused = client.post(
        f"/admin/conversations/{conversation_id}/messages",
        json={"text": "je réponds sans avoir pris le dossier", "agent_id": "conseiller-test"},
        headers=ADMIN_HEADERS,
    )
    assert refused.status_code == 409


def test_a_pending_request_can_be_withdrawn(client, conversation_id):
    """« Finalement je n'ai plus besoin d'un conseiller » (intention
    cancel_human_agent_request côté Rasa → action_cancel_human_agent_request
    → cette route)."""
    client.post(
        "/conversations/turns",
        json={"conversation_id": conversation_id, "user_text": "bonjour", "intent": "greet"},
    )
    client.post("/conversations/escalate", json={"conversation_id": conversation_id})

    withdrawn = client.post("/conversations/withdraw", json={"conversation_id": conversation_id})
    assert withdrawn.status_code == 200
    assert withdrawn.json()["withdrawn"] is True
    assert withdrawn.json()["status"] == "BOT"

    # La conversation a quitté la file des conseillers.
    queue = client.get("/admin/conversations/?escalated=true", headers=ADMIN_HEADERS)
    assert all(row["conversation_id"] != conversation_id for row in queue.json())

    # Rejouer l'annulation ne casse rien : l'usager n'a pas à connaître
    # l'état interne de sa conversation.
    again = client.post("/conversations/withdraw", json={"conversation_id": conversation_id})
    assert again.status_code == 200
    assert again.json()["withdrawn"] is True


def test_a_taken_conversation_is_not_withdrawn_behind_the_advisor(client, conversation_id):
    client.post(
        "/conversations/turns",
        json={"conversation_id": conversation_id, "user_text": "bonjour", "intent": "greet"},
    )
    client.post("/conversations/escalate", json={"conversation_id": conversation_id})
    client.post(
        f"/admin/conversations/{conversation_id}/assign",
        json={"agent_id": "conseiller-test"},
        headers=ADMIN_HEADERS,
    )

    refused = client.post("/conversations/withdraw", json={"conversation_id": conversation_id})
    assert refused.status_code == 200
    # Rien n'est annulé : le conseiller est déjà engagé sur le dossier.
    assert refused.json()["withdrawn"] is False
    assert refused.json()["status"] == "PRISE_EN_CHARGE"
    assert refused.json()["assigned_to"] == "conseiller-test"


def test_support_users_are_aggregated_not_stored(client, conversation_id):
    client.post(
        "/conversations/turns",
        json={
            "conversation_id": conversation_id,
            "user_id": "usager-test-42",
            "user_text": "bonjour",
            "intent": "greet",
        },
    )
    listed = client.get("/admin/users/?limit=200", headers=ADMIN_HEADERS)
    assert listed.status_code == 200
    assert any(user["user_id"] == "usager-test-42" for user in listed.json())

    detail = client.get("/admin/users/usager-test-42", headers=ADMIN_HEADERS)
    assert detail.status_code == 200
    body = detail.json()
    assert body["messages_sent"] >= 1
    # Aucune donnée de profil n'est inventée : ce domaine n'a pas de table.
    assert "display_name" not in body and "email" not in body

    assert client.get("/admin/users/personne-inconnue", headers=ADMIN_HEADERS).status_code == 404


def test_dashboard_endpoints_answer_with_real_shapes(client):
    summary = client.get("/admin/dashboard/summary?days=7", headers=ADMIN_HEADERS)
    assert summary.status_code == 200
    assert "conversations_in_progress" in summary.json()

    volume = client.get("/admin/dashboard/conversation-volume?days=7", headers=ADMIN_HEADERS)
    assert volume.status_code == 200
    assert len(volume.json()["points"]) == 7

    intents = client.get("/admin/dashboard/intent-distribution?days=7", headers=ADMIN_HEADERS)
    assert intents.status_code == 200
    assert sum(slice_["count"] for slice_ in intents.json()["categories"]) == intents.json()[
        "total_messages"
    ]

    runs = client.get("/admin/diagnostics/runs?days=7", headers=ADMIN_HEADERS)
    assert runs.status_code == 200
    assert len(runs.json()["points"]) == 7

    # Compteurs de navigation servis par le meme appel que les KPI.
    for counter in ("conversations_total", "tickets_open", "agents_online", "users_total"):
        assert counter in summary.json()


def test_memory_recalls_previous_conversation_of_same_user(client, conversation_id):
    """Memoire entre conversations (docs/20-memoire-conversationnelle.md) :
    une nouvelle conversation du MEME utilisateur retrouve le sujet de la
    precedente ; la conversation en cours n'est jamais rappelee a elle-meme,
    et une conversation sans sujet reel ("bonjour" seul) est ignoree."""
    user_id = f"test-user-{uuid.uuid4().hex[:8]}"
    current = f"{conversation_id}-b"
    try:
        client.post("/conversations/turns", json={
            "conversation_id": conversation_id, "user_id": user_id,
            "user_text": "mon retrait est bloqué depuis hier", "intent": "diagnostic",
        })
        client.post("/conversations/turns", json={
            "conversation_id": current, "user_id": user_id,
            "user_text": "bonjour", "intent": "greet",
        })

        memory = client.get("/conversations/memory", params={"user_id": user_id, "exclude": current}).json()
        assert memory["found"] is True
        assert memory["conversation_id"] == conversation_id
        assert memory["topic"] == "mon retrait est bloqué depuis hier"
        assert memory["topic_intent"] == "diagnostic"

        # Exclure la seule conversation qui porte un sujet : rien a rappeler.
        empty = client.get("/conversations/memory", params={"user_id": user_id, "exclude": conversation_id}).json()
        assert empty["found"] is False
    finally:
        db = SessionLocal()
        db.query(ConversationMessage).filter(ConversationMessage.conversation_id == current).delete()
        db.query(Conversation).filter(Conversation.conversation_id == current).delete()
        db.commit()
        db.close()
