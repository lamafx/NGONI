"""Parcours complet de la prise en charge humaine, contre une VRAIE base.

Contrairement aux autres tests de ce dossier (session factice, voir
test_ticket_creation.py), ce parcours ne se teste pas avec un faux
repository : ce qu'il faut verifier est precisement ce que fait Postgres --
les contraintes CHECK sur les statuts, la cascade de suppression des
messages, et la requete fenetree du temps de reponse moyen. Un faux le
laisserait passer quoi qu'il arrive.

Le test est donc ignore (skip) si aucune base n'est joignable, plutot que de
faire echouer une suite lancee sur un poste sans Postgres.
"""

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.domains.agents.service import AgentService  # noqa: E402
from app.domains.conversations.models import (  # noqa: E402
    STATUS_ASSIGNED,
    STATUS_BOT,
    STATUS_ESCALATED,
    STATUS_RESOLVED,
    Conversation,
    ConversationMessage,
)
from app.domains.conversations.service import (  # noqa: E402
    ConversationService,
    ConversationStateError,
)
from app.domains.stats.dashboard_service import DashboardService  # noqa: E402


@pytest.fixture
def session():
    try:
        db = SessionLocal()
        db.execute(ConversationMessage.__table__.select().limit(1))
    except Exception as error:  # pragma: no cover - depend de l'environnement
        pytest.skip(f"PostgreSQL indisponible : {error}")
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def conversation_id(session):
    # Identifiant unique par execution : le test peut tourner sur une base de
    # developpement deja peuplee sans rien perturber, et se nettoie ensuite.
    generated = f"test-conv-{uuid.uuid4().hex[:12]}"
    yield generated
    session.query(ConversationMessage).filter(
        ConversationMessage.conversation_id == generated
    ).delete()
    session.query(Conversation).filter(Conversation.conversation_id == generated).delete()
    session.commit()


def test_full_handoff_lifecycle(session, conversation_id):
    service = ConversationService.from_session(session)

    # 1. L'utilisateur parle : la conversation existe, le bot est aux commandes.
    service.record_user_message(
        conversation_id, "mon retrait est bloqué", intent="diagnostic", confidence=0.91
    )
    service.record_bot_messages(conversation_id, [{"text": "Je vérifie votre retrait."}])
    assert service.repository.get(conversation_id).status == STATUS_BOT
    assert service.is_muted(conversation_id) is False

    # 2. Escalade : la conversation entre dans la file, mais le bot repond
    #    toujours tant que personne ne l'a prise.
    service.escalate(conversation_id, reason="demande_utilisateur")
    assert service.repository.get(conversation_id).status == STATUS_ESCALATED
    assert service.is_muted(conversation_id) is False

    # 3. Prise en charge : le bot se tait.
    service.assign(conversation_id, "agent-test")
    assert service.repository.get(conversation_id).status == STATUS_ASSIGNED
    assert service.is_muted(conversation_id) is True

    # 4. Un autre conseiller ne peut pas la voler sans le dire explicitement.
    with pytest.raises(ConversationStateError):
        service.assign(conversation_id, "agent-autre")
    service.assign(conversation_id, "agent-autre", force=True)
    service.assign(conversation_id, "agent-test", force=True)

    # 5. Le conseiller repond ; l'utilisateur recupere le message par la
    #    route de rattrapage, sans que Rasa soit implique.
    service.post_agent_message(conversation_id, "Bonjour, je reprends votre dossier.", "agent-test")
    updates = service.updates_for_user(conversation_id)
    assert updates["handoff"] is True
    assert any(
        message.sender_role == "agent" and "reprends" in message.text
        for message in updates["messages"]
    )
    # Les messages de l'utilisateur ne lui sont jamais renvoyes (doublons).
    assert all(message.sender_role != "user" for message in updates["messages"])

    # 6. Resolution : la conversation sort de la file, et le message suivant
    #    de l'utilisateur rend la main au bot.
    service.resolve(conversation_id, "agent-test", note="Remboursement lancé.")
    assert service.repository.get(conversation_id).status == STATUS_RESOLVED
    service.record_user_message(conversation_id, "merci !", intent="goodbye", confidence=0.99)
    assert service.repository.get(conversation_id).status == STATUS_BOT
    assert service.is_muted(conversation_id) is False


def test_context_is_built_from_real_traces(session, conversation_id):
    service = ConversationService.from_session(session)
    service.record_user_message(conversation_id, "bonjour", intent="greet", confidence=0.99)
    service.record_bot_messages(conversation_id, [{"text": "Bonjour !"}])
    service.record_user_message(conversation_id, "paiement refusé", intent="diagnostic", confidence=0.8)
    service.escalate(conversation_id, reason="diagnostic_echoue")

    context = service.build_context(conversation_id)
    assert context.user_messages == 2
    assert context.bot_messages == 1
    assert set(context.intents_seen) == {"greet", "diagnostic"}
    assert context.escalation_reason == "diagnostic_echoue"
    assert [entry.kind for entry in context.timeline][0] == "conversation"
    assert any(entry.kind == "escalade" for entry in context.timeline)


def test_intent_distribution_counts_real_classifications(session, conversation_id):
    service = ConversationService.from_session(session)
    service.record_user_message(conversation_id, "une question", intent="ask_faq", confidence=0.7)
    service.record_user_message(conversation_id, "/select_faq_category{}", intent=None)

    distribution = DashboardService.from_session(session).intent_distribution(days=1)
    counted = {slice_.intent: slice_.count for slice_ in distribution.categories}
    assert counted.get("ask_faq", 0) >= 1
    # Les payloads structures (clic sur un bouton) ne sont jamais comptes
    # comme des intentions predites.
    assert distribution.unclassified >= 1


def test_avg_response_time_uses_window_query(session, conversation_id):
    """Verifie surtout que la requete fenetree s'execute reellement contre
    Postgres (syntaxe, schema, types) -- la valeur exacte depend du temps
    machine entre les deux insertions."""
    service = ConversationService.from_session(session)
    service.record_user_message(conversation_id, "bloqué", intent="diagnostic", confidence=0.5)
    service.record_bot_messages(conversation_id, [{"text": "Je regarde."}])

    summary = DashboardService.from_session(session).summary(days=1)
    assert summary.avg_response_time_ms.value is not None
    assert summary.conversations_in_progress.value >= 1


def test_agent_presence_is_derived_not_declared(session):
    agent_id = f"test-agent-{uuid.uuid4().hex[:8]}"
    service = AgentService.from_session(session)
    try:
        created = service.create(agent_id, "Conseiller Test", "conseiller")
        # Cree sans activite : declare hors ligne, donc hors ligne.
        assert created.status == "offline"
        online = service.set_status(agent_id, "online")
        assert online.status == "online"
        assert online.declared_status == "online"
    finally:
        from app.domains.agents.models import SupportAgent

        session.query(SupportAgent).filter(SupportAgent.agent_id == agent_id).delete()
        session.commit()
