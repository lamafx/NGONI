"""Historique de dialogue materialise cote FastAPI (voir
migrations/0016_conversations_supervision.sql pour le choix d'architecture :
table propre alimentee par POST /api/chat, PAS une lecture du tracker store
interne de Rasa).

Porte trois besoins qui n'avaient aucun support jusqu'ici :
  - la prise en charge d'une conversation par un conseiller humain (cas
    d'utilisation "Prendre en charge une demande" / "Escalader vers un agent
    humain" du diagramme) ;
  - la restitution de l'historique a ce conseiller quand il reprend la main ;
  - la telemetrie d'intentions (colonne `intent` ci-dessous), prerequis de
    GET /admin/dashboard/intent-distribution.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

try:
    from app.models import Base
except ImportError:  # pragma: no cover - support running as `main`
    from models import Base

# Etats d'une conversation. Volontairement distincts du cycle de vie d'un
# TICKET (complaints.status : OPEN/IN_PROGRESS/RESOLVED/CLOSED) : une
# conversation peut etre prise en charge sans qu'aucun ticket n'existe, et un
# ticket peut vivre longtemps apres la fin de la conversation qui l'a cree.
STATUS_BOT = "BOT"
STATUS_ESCALATED = "ESCALADE_DEMANDEE"
STATUS_ASSIGNED = "PRISE_EN_CHARGE"
STATUS_RESOLVED = "RESOLUE"
ALLOWED_STATUSES = {STATUS_BOT, STATUS_ESCALATED, STATUS_ASSIGNED, STATUS_RESOLVED}

SENDER_ROLES = {"user", "bot", "agent"}


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = {"schema": "ia"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(String, nullable=False, unique=True)
    user_id = Column(String, nullable=True)
    channel = Column(String, nullable=False, default="web")
    status = Column(String, nullable=False, default=STATUS_BOT)
    escalated = Column(Boolean, nullable=False, default=False)
    escalation_reason = Column(String, nullable=True)
    escalated_at = Column(DateTime(timezone=True), nullable=True)
    assigned_to = Column(String, nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    ticket_id = Column(String, nullable=True)
    last_intent = Column(String, nullable=True)
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    message_count = Column(Integer, nullable=False, default=0)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = {"schema": "ia"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(String, nullable=False)
    sender_role = Column(String, nullable=False)
    agent_id = Column(String, nullable=True)
    text = Column(String, nullable=False)
    intent = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    message_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
