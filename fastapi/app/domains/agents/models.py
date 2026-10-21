"""Conseillers (agents humains) du support -- voir
migrations/0016_conversations_supervision.sql.

Remplace le tableau statique AGENTS de frontend/src/data/mockData.js. Ce
n'est PAS un annuaire d'identites : il n'y a ni mot de passe, ni session, ni
role verifie ici (voir docs/13-limitations.md §13.1 -- l'authentification
reste hors perimetre). C'est la liste des personnes a qui une conversation
ou un ticket peut etre attribue, et rien de plus."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

try:
    from app.models import Base
except ImportError:  # pragma: no cover - support running as `main`
    from models import Base

STATUS_ONLINE = "online"
STATUS_AWAY = "away"
STATUS_OFFLINE = "offline"
ALLOWED_STATUSES = {STATUS_ONLINE, STATUS_AWAY, STATUS_OFFLINE}


class SupportAgent(Base):
    __tablename__ = "support_agents"
    __table_args__ = {"schema": "ia"}

    agent_id = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    role = Column(String, nullable=False, default="conseiller")
    status = Column(String, nullable=False, default=STATUS_OFFLINE)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
