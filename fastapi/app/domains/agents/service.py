"""Lecture/ecriture de l'annuaire des conseillers, et surtout : calcul du
statut EFFECTIF et de la charge reelle.

Le statut declare seul ne vaut rien -- personne ne pense a se declarer
"absent" en partant. Toute action d'un conseiller (prise en charge, reponse,
resolution) appelle `touch()`, et un conseiller sans activite depuis
PRESENCE_TIMEOUT_MINUTES est presente comme hors ligne quel que soit le
champ en base."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

try:
    from app.domains.complaints.models import Complaint
    from app.domains.conversations.models import STATUS_ASSIGNED, Conversation
except ImportError:  # pragma: no cover - support running as `main`
    from domains.complaints.models import Complaint
    from domains.conversations.models import STATUS_ASSIGNED, Conversation

from .models import ALLOWED_STATUSES, STATUS_OFFLINE, SupportAgent
from .schemas import AgentResponse

# Au-dela de ce delai sans aucune action, un conseiller est considere hors
# ligne. 15 minutes : assez long pour ne pas faire disparaitre quelqu'un qui
# lit un dossier, assez court pour ne pas router une conversation vers un
# poste vide.
PRESENCE_TIMEOUT_MINUTES = 15


class UnknownAgentError(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


class AgentService:
    def __init__(self, session: Session) -> None:
        self.session = session

    @classmethod
    def from_session(cls, session: Session) -> "AgentService":
        return cls(session)

    # ---- lecture ---------------------------------------------------------

    def list_agents(self) -> List[AgentResponse]:
        agents = self.session.query(SupportAgent).order_by(SupportAgent.display_name).all()
        conversation_load = dict(
            self.session.query(Conversation.assigned_to, func.count())
            .filter(Conversation.status == STATUS_ASSIGNED, Conversation.assigned_to.isnot(None))
            .group_by(Conversation.assigned_to)
            .all()
        )
        ticket_load = dict(
            self.session.query(Complaint.assigned_to, func.count())
            .filter(Complaint.assigned_to.isnot(None), Complaint.status.notin_(["RESOLVED", "CLOSED"]))
            .group_by(Complaint.assigned_to)
            .all()
        )
        return [
            self._to_response(
                agent,
                active_conversations=int(conversation_load.get(agent.agent_id, 0)),
                assigned_tickets=int(ticket_load.get(agent.agent_id, 0)),
            )
            for agent in agents
        ]

    def get_agent(self, agent_id: str) -> AgentResponse:
        agent = self.session.get(SupportAgent, agent_id)
        if agent is None:
            raise UnknownAgentError(agent_id)
        active = (
            self.session.query(func.count())
            .select_from(Conversation)
            .filter(Conversation.assigned_to == agent_id, Conversation.status == STATUS_ASSIGNED)
            .scalar()
        )
        tickets = (
            self.session.query(func.count())
            .select_from(Complaint)
            .filter(Complaint.assigned_to == agent_id, Complaint.status.notin_(["RESOLVED", "CLOSED"]))
            .scalar()
        )
        return self._to_response(
            agent, active_conversations=int(active or 0), assigned_tickets=int(tickets or 0)
        )

    # ---- ecriture --------------------------------------------------------

    def create(self, agent_id: str, display_name: str, role: str) -> AgentResponse:
        agent = self.session.get(SupportAgent, agent_id)
        if agent is None:
            agent = SupportAgent(agent_id=agent_id, display_name=display_name, role=role)
            self.session.add(agent)
        else:
            # Ni erreur ni doublon : reappeler la creation met a jour la fiche
            # (renommage, changement de role) -- l'identifiant, lui, ne bouge
            # jamais puisqu'il est deja inscrit dans des conversations closes.
            agent.display_name = display_name
            agent.role = role
        self.session.commit()
        self.session.refresh(agent)
        return self.get_agent(agent_id)

    def set_status(self, agent_id: str, status: str) -> AgentResponse:
        if status not in ALLOWED_STATUSES:
            raise ValueError(
                f"Statut inconnu : {status!r} (attendu : {', '.join(sorted(ALLOWED_STATUSES))})"
            )
        agent = self.session.get(SupportAgent, agent_id)
        if agent is None:
            raise UnknownAgentError(agent_id)
        agent.status = status
        agent.last_seen_at = _now()
        self.session.commit()
        return self.get_agent(agent_id)

    def touch(self, agent_id: str) -> None:
        """Marque une activite. Best-effort et silencieux : un conseiller
        inconnu de l'annuaire (identifiant saisi a la main, import a venir)
        ne doit jamais faire echouer la prise en charge qu'il vient de faire
        -- la conversation lui est attribuee quand meme."""
        try:
            agent = self.session.get(SupportAgent, agent_id)
            if agent is None:
                return
            agent.last_seen_at = _now()
            if agent.status == STATUS_OFFLINE:
                agent.status = "online"
            self.session.commit()
        except Exception:  # pragma: no cover - jamais bloquant
            self.session.rollback()

    # ---- interne ---------------------------------------------------------

    def _to_response(
        self, agent: SupportAgent, active_conversations: int, assigned_tickets: int
    ) -> AgentResponse:
        return AgentResponse(
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            role=agent.role,
            declared_status=agent.status,
            status=self.effective_status(agent),
            last_seen_at=_iso(agent.last_seen_at),
            active_conversations=active_conversations,
            assigned_tickets=assigned_tickets,
            created_at=_iso(agent.created_at),
        )

    @staticmethod
    def effective_status(agent: SupportAgent) -> str:
        if agent.status == STATUS_OFFLINE:
            return STATUS_OFFLINE
        if agent.last_seen_at is None:
            return STATUS_OFFLINE
        last_seen = agent.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if _now() - last_seen > timedelta(minutes=PRESENCE_TIMEOUT_MINUTES):
            return STATUS_OFFLINE
        return agent.status
