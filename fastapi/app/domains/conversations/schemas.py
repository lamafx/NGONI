from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    id: str
    sender_role: str
    agent_id: Optional[str] = None
    text: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class ConversationSummaryResponse(BaseModel):
    """Vue "liste" -- sans les messages, qui peuvent etre nombreux : la file
    de l'espace Agent doit rester une seule requete legere meme avec des
    centaines de conversations ouvertes."""

    conversation_id: str
    user_id: Optional[str] = None
    channel: str
    status: str
    escalated: bool
    escalation_reason: Optional[str] = None
    escalated_at: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_at: Optional[str] = None
    ticket_id: Optional[str] = None
    last_intent: Optional[str] = None
    last_message: Optional[str] = None
    last_message_at: Optional[str] = None
    message_count: int = 0
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    created_at: Optional[str] = None


class ConversationDetailResponse(ConversationSummaryResponse):
    messages: List[MessageResponse] = Field(default_factory=list)


class TimelineEntry(BaseModel):
    """Une etape de ce que le systeme a DEJA tente avant l'humain -- reconstruite
    depuis les traces existantes (diagnostic_sessions, agent_actions,
    complaints), jamais inventee."""

    at: Optional[str] = None
    kind: str
    label: str
    detail: Optional[str] = None


class ConversationContextResponse(BaseModel):
    """Ce que lit un conseiller AVANT de repondre : pourquoi la conversation
    lui arrive, ce que le moteur a deja tente, et ou en est le dossier."""

    conversation_id: str
    status: str
    escalated: bool
    escalation_reason: Optional[str] = None
    assigned_to: Optional[str] = None
    last_intent: Optional[str] = None
    intents_seen: List[str] = Field(default_factory=list)
    user_messages: int = 0
    bot_messages: int = 0
    agent_messages: int = 0
    diagnostic: Optional[Dict[str, Any]] = None
    tickets: List[Dict[str, Any]] = Field(default_factory=list)
    timeline: List[TimelineEntry] = Field(default_factory=list)


class AssignRequest(BaseModel):
    model_config = {"extra": "forbid"}

    agent_id: str = Field(min_length=1, max_length=200)


class AgentMessageRequest(BaseModel):
    model_config = {"extra": "forbid"}

    # Meme plafond que ChatRequest.text (app/main.py) : la reponse d'un
    # conseiller traverse exactement le meme fil que celle du bot.
    text: str = Field(min_length=1, max_length=4000)
    agent_id: Optional[str] = Field(default=None, max_length=200)


class ResolveRequest(BaseModel):
    model_config = {"extra": "forbid"}

    agent_id: Optional[str] = Field(default=None, max_length=200)
    # Repasser la main au bot pour la suite de la conversation (defaut) ou
    # clore definitivement -- dans les deux cas la conversation sort de la
    # file du conseiller.
    note: Optional[str] = Field(default=None, max_length=2000)


class EscalateRequest(BaseModel):
    """Escalade demandee depuis le poste CLIENT (bouton "parler a un
    conseiller"), par opposition a l'escalade automatique declenchee cote
    serveur a la creation d'un ticket."""

    model_config = {"extra": "forbid"}

    conversation_id: str = Field(min_length=1, max_length=200)
    user_id: Optional[str] = Field(default=None, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=500)


class WithdrawRequest(BaseModel):
    """Retrait d'une demande de conseiller encore en attente -- l'usager
    prefere finalement continuer avec l'assistant."""

    model_config = {"extra": "forbid"}

    conversation_id: str = Field(min_length=1, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=500)


class WithdrawResponse(BaseModel):
    conversation_id: str
    status: str
    # False quand un conseiller tenait deja la conversation : la demande n'est
    # PAS annulee, et l'appelant doit le dire a l'usager.
    withdrawn: bool
    assigned_to: Optional[str] = None


class ConversationUpdatesResponse(BaseModel):
    """Reponse de l'appel de rattrapage cote client : ce qui a ete dit dans
    la conversation depuis un instant donne, plus l'etat de la prise en
    charge (pour savoir s'il faut continuer a interroger)."""

    conversation_id: str
    status: str
    assigned_to: Optional[str] = None
    handoff: bool = False
    messages: List[MessageResponse] = Field(default_factory=list)
    checked_at: str


class MemoryTicket(BaseModel):
    ticket_id: str
    status: Optional[str] = None
    category: Optional[str] = None
    summary: Optional[str] = None


class ConversationMemoryResponse(BaseModel):
    """Ce dont l'assistant se souvient de la DERNIERE conversation utile d'un
    utilisateur (memoire entre conversations, lue par l'accueil Rasa -- voir
    rasa/actions/greeting.py). `found: false` quand il n'y a rien de
    pertinent a rappeler : jamais de souvenir invente."""

    found: bool = False
    conversation_id: Optional[str] = None
    last_message_at: Optional[str] = None
    topic: Optional[str] = None
    topic_intent: Optional[str] = None
    ticket: Optional[MemoryTicket] = None


class TurnBotMessage(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    # Boutons Rasa et autres decorations du message -- stockes tels quels,
    # jamais interpretes (voir ConversationMessage.message_metadata).
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TurnRequest(BaseModel):
    """Journalisation d'un tour de dialogue par un client qui parle
    DIRECTEMENT au webhook Rasa, sans passer par POST /api/chat (c'est le cas
    de l'interface React : voir frontend/src/services/rasaClient.js).

    Pourquoi cette route existe : le tracker de Rasa n'est expose par aucune
    API publique, et le conseiller qui reprend une conversation a besoin de
    son historique. Les clients qui passent par POST /api/chat sont deja
    journalises cote serveur et n'ont RIEN a envoyer ici (ce serait un
    doublon) -- voir app/main.py.

    Meme niveau de confiance que le reste du perimetre : cette API n'a pas
    d'authentification utilisateur (docs/13-limitations.md 13.1), le contenu
    recu est donc declaratif. Il alimente l'affichage du conseiller et la
    volumetrie, jamais une decision automatique."""

    model_config = {"extra": "forbid"}

    conversation_id: str = Field(min_length=1, max_length=200)
    user_id: Optional[str] = Field(default=None, max_length=200)
    user_text: str = Field(min_length=1, max_length=4000)
    intent: Optional[str] = Field(default=None, max_length=200)
    confidence: Optional[float] = None
    bot_messages: List[TurnBotMessage] = Field(default_factory=list)


class TurnResponse(BaseModel):
    conversation_id: str
    status: str
    # Vrai quand un conseiller a pris la conversation : le client doit alors
    # cesser d'interroger Rasa et attendre les reponses humaines.
    handoff: bool
    assigned_to: Optional[str] = None
