"""Les usagers VUS PAR LE SUPPORT -- pas un annuaire d'identites.

Ce domaine ne possede aucune table, comme `stats` : il agrege ce que les
autres ecrivent (`ia.conversations`, `ia.complaints`). C'est une decision,
pas un raccourci : `docs/03-taxonomie.md` place les profils/KYC dans
`ngoni-user-service` (Laravel, hors perimetre de ce depot). Recreer ici une
table `users` en dupliquerait la source de verite, et ferait diverger deux
bases des la premiere modification de profil.

Ce qui est donc renvoye ici : l'identifiant sous lequel la personne a
contacte le support, son volume d'echanges, ses tickets, sa derniere
activite. Aucun nom, aucun email, aucune donnee de profil -- ces
informations n'existent pas dans le schema `ia`, et en inventer un affichage
serait pire que de ne rien montrer. Le jour ou ngoni-user-service est
joignable, ces routes deviennent un enrichissement (proxy) plutot qu'une
nouvelle table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

try:
    from app.domains.complaints.models import Complaint
    from app.domains.conversations.models import Conversation, ConversationMessage
except ImportError:  # pragma: no cover - support running as `main`
    from domains.complaints.models import Complaint
    from domains.conversations.models import Conversation, ConversationMessage

from .schemas import SupportUserDetailResponse, SupportUserResponse


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _max_iso(*values: Optional[datetime]) -> Optional[str]:
    known = [value for value in values if value is not None]
    return _iso(max(known)) if known else None


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session

    @classmethod
    def from_session(cls, session: Session) -> "UserService":
        return cls(session)

    # Identite retenue : `user_id` quand il est connu, sinon l'identifiant de
    # conversation. Une conversation anonyme (page /chat sans utilisateur
    # connecte) reste une personne a laquelle le support a parle -- la
    # masquer donnerait un compteur d'usagers faux.
    _IDENTITY = func.coalesce(Conversation.user_id, Conversation.conversation_id)

    def list_users(self, limit: int = 50, offset: int = 0) -> List[SupportUserResponse]:
        rows = (
            self.session.query(
                self._IDENTITY.label("user_id"),
                func.count(Conversation.conversation_id).label("conversations"),
                func.max(Conversation.last_message_at).label("last_activity"),
                # cast explicite : SUM sur un booleen n'est pas portable, et
                # Postgres le refuse tout court.
                func.sum(cast(Conversation.escalated, Integer)).label("escalations"),
            )
            # Sur l'EXPRESSION, pas sur l'alias "user_id" : Postgres le
            # rapprocherait de la colonne conversations.user_id du meme nom
            # (ambiguite refusee), et le regroupement serait faux.
            .group_by(self._IDENTITY)
            .order_by(func.max(Conversation.last_message_at).desc().nullslast())
            .limit(limit)
            .offset(offset)
            .all()
        )
        if not rows:
            return []

        identities = [row.user_id for row in rows]
        ticket_counts = dict(
            self.session.query(Complaint.user_id, func.count())
            .filter(Complaint.user_id.in_(identities))
            .group_by(Complaint.user_id)
            .all()
        )
        open_ticket_counts = dict(
            self.session.query(Complaint.user_id, func.count())
            .filter(
                Complaint.user_id.in_(identities),
                Complaint.status.notin_(["RESOLVED", "CLOSED"]),
            )
            .group_by(Complaint.user_id)
            .all()
        )
        return [
            SupportUserResponse(
                user_id=row.user_id,
                conversations=int(row.conversations or 0),
                escalations=int(row.escalations or 0),
                tickets=int(ticket_counts.get(row.user_id, 0)),
                open_tickets=int(open_ticket_counts.get(row.user_id, 0)),
                last_activity=_iso(row.last_activity),
            )
            for row in rows
        ]

    def get_user(self, user_id: str) -> Optional[SupportUserDetailResponse]:
        conversations = (
            self.session.query(Conversation)
            .filter((Conversation.user_id == user_id) | (Conversation.conversation_id == user_id))
            .order_by(Conversation.last_message_at.desc().nullslast())
            .limit(50)
            .all()
        )
        tickets = (
            self.session.query(Complaint)
            .filter(Complaint.user_id == user_id)
            .order_by(Complaint.created_at.desc())
            .limit(50)
            .all()
        )
        if not conversations and not tickets:
            return None

        messages_sent = 0
        if conversations:
            messages_sent = int(
                self.session.query(func.count())
                .select_from(ConversationMessage)
                .filter(
                    ConversationMessage.conversation_id.in_(
                        [conversation.conversation_id for conversation in conversations]
                    ),
                    ConversationMessage.sender_role == "user",
                )
                .scalar()
                or 0
            )

        conversation_rows: List[Dict[str, Any]] = [
            {
                "conversation_id": conversation.conversation_id,
                "status": conversation.status,
                "escalated": conversation.escalated,
                "assigned_to": conversation.assigned_to,
                "last_intent": conversation.last_intent,
                "message_count": conversation.message_count or 0,
                "last_message_at": _iso(conversation.last_message_at),
            }
            for conversation in conversations
        ]
        ticket_rows: List[Dict[str, Any]] = [
            {
                "ticket_id": ticket.ticket_id,
                "category": ticket.category,
                "urgency": ticket.urgency,
                "status": ticket.status,
                "assigned_to": ticket.assigned_to,
                "summary": ticket.summary,
                "created_at": _iso(ticket.created_at),
            }
            for ticket in tickets
        ]

        return SupportUserDetailResponse(
            user_id=user_id,
            conversations=len(conversations),
            escalations=sum(1 for conversation in conversations if conversation.escalated),
            tickets=len(tickets),
            open_tickets=sum(
                1 for ticket in tickets if ticket.status not in ("RESOLVED", "CLOSED")
            ),
            messages_sent=messages_sent,
            last_activity=_max_iso(
                *[conversation.last_message_at for conversation in conversations],
                *[ticket.created_at for ticket in tickets],
            ),
            conversation_list=conversation_rows,
            ticket_list=ticket_rows,
        )
