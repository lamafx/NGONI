"""Acces SQL aux deux tables du domaine. Aucune regle metier ici (voir
service.py) : le repository ne decide jamais d'un changement de statut, il
l'ecrit."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Conversation, ConversationMessage


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---- conversations ---------------------------------------------------

    def get(self, conversation_id: str) -> Optional[Conversation]:
        stmt = select(Conversation).where(Conversation.conversation_id == conversation_id)
        return self.session.execute(stmt).scalars().first()

    def get_or_create(
        self, conversation_id: str, user_id: Optional[str] = None, channel: str = "web"
    ) -> Conversation:
        conversation = self.get(conversation_id)
        if conversation is None:
            conversation = Conversation(
                conversation_id=conversation_id, user_id=user_id, channel=channel
            )
            self.session.add(conversation)
            self.session.commit()
            self.session.refresh(conversation)
        elif user_id and (
            not conversation.user_id
            or (conversation.user_id == conversation_id and user_id != conversation_id)
        ):
            # L'identite reelle peut n'arriver qu'apres coup (premier message
            # anonyme, puis connexion) -- on l'enregistre sans jamais ecraser
            # une identite deja connue par un None. Seule exception : une
            # identite qui n'etait que l'identifiant de conversation lui-meme
            # (ecrite par la creation de ticket, voir complaints/router.py,
            # quand elle precede le premier tour journalise) est remplacee
            # par l'identite stable de l'utilisateur des qu'elle arrive.
            conversation.user_id = user_id
            self.session.commit()
        return conversation

    def list_for_user(
        self, user_id: str, exclude_conversation_id: Optional[str] = None, limit: int = 10
    ) -> List[Conversation]:
        """Conversations precedentes d'un meme utilisateur, la plus recente
        d'abord -- base de la memoire entre conversations (voir
        ConversationService.memory_for_user)."""
        query = self.session.query(Conversation).filter(Conversation.user_id == user_id)
        if exclude_conversation_id:
            query = query.filter(Conversation.conversation_id != exclude_conversation_id)
        return (
            query.order_by(Conversation.last_message_at.desc().nullslast())
            .limit(limit)
            .all()
        )

    def list(
        self,
        status: Optional[str] = None,
        assigned_to: Optional[str] = None,
        escalated: Optional[bool] = None,
        unassigned: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Conversation]:
        query = self.session.query(Conversation)
        if status is not None:
            query = query.filter(Conversation.status == status)
        if assigned_to is not None:
            query = query.filter(Conversation.assigned_to == assigned_to)
        if escalated is not None:
            query = query.filter(Conversation.escalated.is_(escalated))
        if unassigned:
            query = query.filter(Conversation.assigned_to.is_(None))
        return (
            query.order_by(Conversation.last_message_at.desc().nullslast())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def save(self, conversation: Conversation) -> Conversation:
        conversation.updated_at = _now()
        self.session.commit()
        self.session.refresh(conversation)
        return conversation

    # ---- messages --------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        sender_role: str,
        text: str,
        intent: Optional[str] = None,
        confidence: Optional[float] = None,
        agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation_id,
            sender_role=sender_role,
            text=text,
            intent=intent,
            confidence=confidence,
            agent_id=agent_id,
            message_metadata=metadata or {},
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def list_messages(
        self, conversation_id: str, after: Optional[datetime] = None, limit: int = 500
    ) -> List[ConversationMessage]:
        query = self.session.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conversation_id
        )
        if after is not None:
            query = query.filter(ConversationMessage.created_at > after)
        return query.order_by(ConversationMessage.created_at.asc()).limit(limit).all()

    def last_message_text(self, conversation_id: str) -> Optional[str]:
        stmt = (
            select(ConversationMessage.text)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()

    def last_message(self, conversation_id: str) -> tuple[Optional[str], Optional[str]]:
        """(texte, role de l'auteur) du dernier message -- le role permet aux
        notifications du conseiller d'ignorer ses propres reponses."""
        stmt = (
            select(ConversationMessage.text, ConversationMessage.sender_role)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(1)
        )
        row = self.session.execute(stmt).first()
        return (row[0], row[1]) if row else (None, None)

    def count_by_role(self, conversation_id: str) -> Dict[str, int]:
        stmt = (
            select(ConversationMessage.sender_role, func.count())
            .where(ConversationMessage.conversation_id == conversation_id)
            .group_by(ConversationMessage.sender_role)
        )
        return {role: int(count) for role, count in self.session.execute(stmt).all()}

    def distinct_intents(self, conversation_id: str) -> List[str]:
        stmt = (
            select(ConversationMessage.intent)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.intent.isnot(None),
            )
            .distinct()
        )
        return [intent for intent in self.session.execute(stmt).scalars().all() if intent]
