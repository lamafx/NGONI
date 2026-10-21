"""Regles de la prise en charge humaine.

Le point dur du domaine tient en une phrase : quand un conseiller prend une
conversation, le bot doit se TAIRE. Sans cela, l'utilisateur recevrait deux
reponses concurrentes au meme message (celle du conseiller et celle de Rasa),
et le conseiller ecrirait par-dessus un dialogue que le moteur continue de
piloter de son cote.

Ce silence est impose ici, cote FastAPI (voir `is_muted`, applique par
POST /api/chat dans app/main.py), et NON cote Rasa : POST /api/chat est le
seul chemin par lequel un message utilisateur atteint le moteur depuis le
frontend, le filtrer la suffit. C'est un choix delibere -- le faire cote Rasa
aurait impose un slot de mise en pause, une regle dediee et donc un
reentrainement du modele a chaque evolution de la prise en charge, pour un
resultat identique du point de vue de l'utilisateur.

Une seule chose a ete ajoutee cote Rasa, et elle ne pouvait pas l'etre
ailleurs : l'intention `cancel_human_agent_request` (« finalement, plus
besoin de conseiller »), qui demande de COMPRENDRE une phrase -- voir
`withdraw` plus bas et rasa/actions/handoff.py. Le silence du bot, lui,
reste entierement ici.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .models import (
    STATUS_ASSIGNED,
    STATUS_BOT,
    STATUS_ESCALATED,
    STATUS_RESOLVED,
    Conversation,
    ConversationMessage,
)
from .repository import ConversationRepository
from .schemas import (
    ConversationContextResponse,
    ConversationDetailResponse,
    ConversationSummaryResponse,
    MessageResponse,
    TimelineEntry,
)

logger = logging.getLogger(__name__)


class ConversationNotFoundError(LookupError):
    pass


class ConversationStateError(ValueError):
    """Transition refusee (ex. reprendre une conversation deja tenue par un
    autre conseiller)."""


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Intentions qui portent un vrai SUJET dont il vaut la peine de se souvenir
# d'une conversation a l'autre -- pas la politesse, ni les oui/non, ni les
# clics de navigation FAQ.
MEMORABLE_INTENTS = {"diagnostic", "create_reclamation", "plainte", "ask_faq", "suggestion"}
# Au-dela, rappeler "la derniere fois" n'aide plus personne.
MEMORY_MAX_AGE_DAYS = 30


class ConversationService:
    def __init__(self, repository: ConversationRepository) -> None:
        self.repository = repository

    @classmethod
    def from_session(cls, session: Session) -> "ConversationService":
        return cls(ConversationRepository(session))

    # ---- flux utilisateur ------------------------------------------------

    def is_muted(self, conversation_id: str) -> bool:
        """Le bot doit-il se taire sur cette conversation ? Vrai uniquement
        quand un conseiller l'a effectivement prise en charge -- une simple
        demande d'escalade (ESCALADE_DEMANDEE) ne coupe PAS le bot : tant que
        personne n'a repris la main, laisser l'utilisateur sans aucune reponse
        serait pire que de continuer a l'aider."""
        conversation = self.repository.get(conversation_id)
        return conversation is not None and conversation.status == STATUS_ASSIGNED

    def record_user_message(
        self,
        conversation_id: str,
        text: str,
        user_id: Optional[str] = None,
        intent: Optional[str] = None,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Conversation:
        conversation = self.repository.get_or_create(conversation_id, user_id=user_id)
        self.repository.add_message(
            conversation_id,
            sender_role="user",
            text=text,
            intent=intent,
            confidence=confidence,
            metadata=metadata,
        )
        # Une conversation close que l'utilisateur relance repart au bot : le
        # conseiller qui l'avait resolue n'a aucune raison d'etre rappele sur
        # un sujet peut-etre sans rapport, des heures plus tard.
        if conversation.status == STATUS_RESOLVED:
            conversation.status = STATUS_BOT
            conversation.escalated = False
            conversation.escalation_reason = None
            conversation.assigned_to = None
            conversation.assigned_at = None
        if intent:
            conversation.last_intent = intent
        conversation.last_message_at = _now()
        conversation.message_count = (conversation.message_count or 0) + 1
        return self.repository.save(conversation)

    def record_bot_messages(self, conversation_id: str, messages: List[Dict[str, Any]]) -> None:
        conversation = self.repository.get(conversation_id)
        if conversation is None:
            return
        stored = 0
        for message in messages:
            text = (message or {}).get("text")
            if not text:
                continue
            metadata = {
                key: value
                for key, value in (message or {}).items()
                if key not in {"text", "recipient_id"} and value is not None
            }
            self.repository.add_message(
                conversation_id, sender_role="bot", text=text, metadata=metadata
            )
            stored += 1
        if stored:
            conversation.message_count = (conversation.message_count or 0) + stored
            conversation.last_message_at = _now()
            self.repository.save(conversation)

    def escalate(
        self,
        conversation_id: str,
        reason: Optional[str] = None,
        ticket_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Conversation:
        """Place la conversation dans la file des conseillers. Idempotent :
        deux tickets crees dans la meme conversation ne la font pas remonter
        deux fois, et n'ecrasent pas le conseiller qui l'a deja prise."""
        conversation = self.repository.get_or_create(conversation_id, user_id=user_id)
        if ticket_id:
            conversation.ticket_id = ticket_id
        if conversation.status == STATUS_ASSIGNED:
            return self.repository.save(conversation)
        if not conversation.escalated:
            conversation.escalated = True
            conversation.escalated_at = _now()
            conversation.escalation_reason = reason
        elif reason and not conversation.escalation_reason:
            conversation.escalation_reason = reason
        conversation.status = STATUS_ESCALATED
        return self.repository.save(conversation)

    def withdraw(self, conversation_id: str, reason: Optional[str] = None) -> tuple[bool, Conversation]:
        """Annule une demande de conseiller encore en attente.

        Refuse (sans rien casser) quand un conseiller a DEJA pris la
        conversation : a ce stade une personne est engagee sur le dossier,
        la faire disparaitre de sa file sur un message de l'usager la
        laisserait ecrire dans le vide. L'appelant recoit alors False et
        formule la reponse en consequence -- voir
        rasa/actions/handoff.py::ActionCancelHumanAgentRequest.

        Renvoie (annulee, conversation)."""
        conversation = self.repository.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        if conversation.status == STATUS_ASSIGNED:
            return False, conversation
        if conversation.status != STATUS_ESCALATED:
            # Rien a annuler : l'assistant repondait deja. Idempotent plutot
            # qu'une erreur -- l'usager n'a pas a savoir dans quel etat
            # interne se trouvait sa conversation.
            return True, conversation
        conversation.status = STATUS_BOT
        conversation.escalated = False
        conversation.escalated_at = None
        # La raison d'origine est remplacee par celle du retrait : garder
        # "demande_utilisateur" sur une demande annulee ferait apparaitre une
        # escalade fantome dans l'activite recente.
        conversation.escalation_reason = reason or "annulee_par_usager"
        return True, self.repository.save(conversation)

    def memory_for_user(
        self, user_id: str, exclude_conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Dernier sujet reel aborde par cet utilisateur dans une conversation
        PRECEDENTE (la conversation en cours est exclue), et le ticket qui en
        est ne s'il y en a un, avec son statut ACTUEL -- c'est ce que
        l'assistant rappelle a l'accueil. Tout vient de ce qui a ete
        journalise ou cree, rien n'est deduit."""
        session = self.repository.session
        oldest = _now().timestamp() - MEMORY_MAX_AGE_DAYS * 86400
        for conversation in self.repository.list_for_user(user_id, exclude_conversation_id):
            last_at = conversation.last_message_at
            if last_at is not None and last_at.timestamp() < oldest:
                break

            topic_message = next(
                (
                    m
                    for m in self.repository.list_messages(conversation.conversation_id, limit=200)
                    if m.sender_role == "user"
                    and m.intent in MEMORABLE_INTENTS
                    and not m.text.startswith("/")
                ),
                None,
            )

            ticket = None
            try:
                try:
                    from app.domains.complaints.models import Complaint
                except ImportError:  # pragma: no cover - support running as `main`
                    from domains.complaints.models import Complaint

                query = session.query(Complaint).filter(
                    Complaint.user_id == conversation.conversation_id
                )
                if conversation.ticket_id:
                    query = session.query(Complaint).filter(
                        Complaint.ticket_id == conversation.ticket_id
                    )
                complaint = query.order_by(Complaint.created_at.desc()).first()
                if complaint is not None:
                    ticket = {
                        "ticket_id": complaint.ticket_id,
                        "status": complaint.status,
                        "category": complaint.category,
                        "summary": complaint.summary,
                    }
            except Exception as error:  # pragma: no cover - lecture best-effort
                logger.warning(
                    "Memoire %s : tickets illisibles (%s)", conversation.conversation_id, error
                )

            if topic_message is None and ticket is None:
                # Conversation sans sujet reel (juste un bonjour) : on remonte
                # a la precedente plutot que de "se souvenir" de rien.
                continue
            return {
                "found": True,
                "conversation_id": conversation.conversation_id,
                "last_message_at": _iso(last_at),
                "topic": topic_message.text if topic_message else None,
                "topic_intent": topic_message.intent if topic_message else None,
                "ticket": ticket,
            }
        return {"found": False}

    def updates_for_user(
        self, conversation_id: str, after: Optional[datetime] = None
    ) -> Dict[str, Any]:
        conversation = self.repository.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        messages = [
            _message_response(message)
            for message in self.repository.list_messages(conversation_id, after=after)
            # Les messages de l'utilisateur lui-meme sont deja affiches chez
            # lui : les renvoyer les ferait apparaitre en double.
            if message.sender_role != "user"
        ]
        return {
            "conversation_id": conversation_id,
            "status": conversation.status,
            "assigned_to": conversation.assigned_to,
            "handoff": conversation.status == STATUS_ASSIGNED,
            "messages": messages,
            "checked_at": _now().isoformat(),
        }

    # ---- flux conseiller -------------------------------------------------

    def list_conversations(self, **filters) -> List[ConversationSummaryResponse]:
        return [self._summary(conversation) for conversation in self.repository.list(**filters)]

    def get_detail(self, conversation_id: str) -> ConversationDetailResponse:
        conversation = self._require(conversation_id)
        messages = self.repository.list_messages(conversation_id)
        summary = self._summary(conversation)
        return ConversationDetailResponse(
            **summary.model_dump(),
            messages=[_message_response(message) for message in messages],
        )

    def assign(
        self, conversation_id: str, agent_id: str, force: bool = False
    ) -> ConversationSummaryResponse:
        """« Prendre en charge une demande ». Refuse de voler une conversation
        deja tenue par quelqu'un d'autre (sauf `force`) : deux conseillers qui
        repondent en meme temps au meme utilisateur est exactement ce que
        cette file est censee empecher."""
        conversation = self._require(conversation_id)
        if (
            conversation.status == STATUS_ASSIGNED
            and conversation.assigned_to
            and conversation.assigned_to != agent_id
            and not force
        ):
            raise ConversationStateError(
                f"Conversation déjà prise en charge par {conversation.assigned_to}"
            )
        conversation.assigned_to = agent_id
        conversation.assigned_at = _now()
        conversation.status = STATUS_ASSIGNED
        if not conversation.escalated:
            # Un conseiller peut reprendre une conversation que personne n'a
            # escaladee (supervision proactive) -- on trace alors l'origine
            # reelle plutot que de laisser croire a une demande de l'usager.
            conversation.escalated = True
            conversation.escalated_at = _now()
            conversation.escalation_reason = "prise_en_charge_proactive"
        return self._summary(self.repository.save(conversation))

    def post_agent_message(
        self, conversation_id: str, text: str, agent_id: Optional[str]
    ) -> MessageResponse:
        conversation = self._require(conversation_id)
        if conversation.status != STATUS_ASSIGNED:
            raise ConversationStateError(
                "Prenez d'abord la conversation en charge avant d'y répondre"
            )
        message = self.repository.add_message(
            conversation_id, sender_role="agent", text=text, agent_id=agent_id
        )
        conversation.message_count = (conversation.message_count or 0) + 1
        conversation.last_message_at = _now()
        self.repository.save(conversation)
        return _message_response(message)

    def resolve(
        self, conversation_id: str, agent_id: Optional[str], note: Optional[str] = None
    ) -> ConversationSummaryResponse:
        conversation = self._require(conversation_id)
        conversation.status = STATUS_RESOLVED
        conversation.resolved_at = _now()
        conversation.resolved_by = agent_id
        # assigned_to est CONSERVE : savoir qui a traite la conversation reste
        # utile apres coup (charge par conseiller, reprise du dossier).
        if note:
            self.repository.add_message(
                conversation_id,
                sender_role="agent",
                text=note,
                agent_id=agent_id,
                metadata={"kind": "resolution_note"},
            )
        return self._summary(self.repository.save(conversation))

    def build_context(self, conversation_id: str) -> ConversationContextResponse:
        """Resume de reprise. Tout ce qui est renvoye ici provient de traces
        reellement ecrites par le moteur (messages, diagnostic_sessions,
        complaints) -- aucun resume genere, aucune valeur d'illustration."""
        conversation = self._require(conversation_id)
        session = self.repository.session
        counts = self.repository.count_by_role(conversation_id)
        timeline: List[TimelineEntry] = []

        if conversation.created_at:
            timeline.append(
                TimelineEntry(
                    at=_iso(conversation.created_at),
                    kind="conversation",
                    label="Début de la conversation",
                    detail=conversation.channel,
                )
            )

        diagnostic_payload = None
        try:
            try:
                from app.domains.diagnostic.models import DiagnosticAuditLog, DiagnosticSession
            except ImportError:  # pragma: no cover - support running as `main`
                from domains.diagnostic.models import DiagnosticAuditLog, DiagnosticSession

            diagnostic = (
                session.query(DiagnosticSession)
                .filter(DiagnosticSession.session_id == conversation_id)
                .first()
            )
            if diagnostic is not None:
                diagnostic_payload = {
                    "service": diagnostic.service,
                    "problem": diagnostic.problem,
                    "status": diagnostic.status,
                    "last_outcome": diagnostic.last_outcome,
                    "turns_count": diagnostic.turns_count,
                    "updated_at": _iso(diagnostic.updated_at),
                }
            for entry in (
                session.query(DiagnosticAuditLog)
                .filter(DiagnosticAuditLog.session_id == conversation_id)
                .order_by(DiagnosticAuditLog.created_at.asc())
                .limit(50)
                .all()
            ):
                timeline.append(
                    TimelineEntry(
                        at=_iso(entry.created_at),
                        kind="diagnostic",
                        label=f"Diagnostic {entry.service} / {entry.problem} → {entry.outcome}",
                        detail=entry.outcome_detail,
                    )
                )
        except Exception as error:  # pragma: no cover - lecture best-effort
            logger.warning(
                "Contexte conversation %s : diagnostic illisible (%s)", conversation_id, error
            )

        tickets: List[Dict[str, Any]] = []
        try:
            try:
                from app.domains.complaints.models import Complaint
            except ImportError:  # pragma: no cover - support running as `main`
                from domains.complaints.models import Complaint

            query = session.query(Complaint).filter(Complaint.user_id == conversation_id)
            if conversation.ticket_id:
                query = session.query(Complaint).filter(
                    (Complaint.user_id == conversation_id)
                    | (Complaint.ticket_id == conversation.ticket_id)
                )
            for complaint in query.order_by(Complaint.created_at.asc()).limit(20).all():
                tickets.append(
                    {
                        "ticket_id": complaint.ticket_id,
                        "category": complaint.category,
                        "urgency": complaint.urgency,
                        "status": complaint.status,
                        "summary": complaint.summary,
                        "assigned_to": getattr(complaint, "assigned_to", None),
                        "created_at": _iso(complaint.created_at),
                    }
                )
                timeline.append(
                    TimelineEntry(
                        at=_iso(complaint.created_at),
                        kind="ticket",
                        label=f"Ticket {complaint.ticket_id} ({complaint.category})",
                        detail=complaint.summary,
                    )
                )
        except Exception as error:  # pragma: no cover - lecture best-effort
            logger.warning(
                "Contexte conversation %s : tickets illisibles (%s)", conversation_id, error
            )

        if conversation.escalated_at:
            timeline.append(
                TimelineEntry(
                    at=_iso(conversation.escalated_at),
                    kind="escalade",
                    label="Escalade vers un conseiller",
                    detail=conversation.escalation_reason,
                )
            )
        if conversation.assigned_at:
            timeline.append(
                TimelineEntry(
                    at=_iso(conversation.assigned_at),
                    kind="prise_en_charge",
                    label="Prise en charge",
                    detail=conversation.assigned_to,
                )
            )

        timeline.sort(key=lambda entry: entry.at or "")
        return ConversationContextResponse(
            conversation_id=conversation_id,
            status=conversation.status,
            escalated=conversation.escalated,
            escalation_reason=conversation.escalation_reason,
            assigned_to=conversation.assigned_to,
            last_intent=conversation.last_intent,
            intents_seen=self.repository.distinct_intents(conversation_id),
            user_messages=counts.get("user", 0),
            bot_messages=counts.get("bot", 0),
            agent_messages=counts.get("agent", 0),
            diagnostic=diagnostic_payload,
            tickets=tickets,
            timeline=timeline,
        )

    # ---- interne ---------------------------------------------------------

    def _require(self, conversation_id: str) -> Conversation:
        conversation = self.repository.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        return conversation

    def _summary(self, conversation: Conversation) -> ConversationSummaryResponse:
        return ConversationSummaryResponse(
            conversation_id=conversation.conversation_id,
            user_id=conversation.user_id,
            channel=conversation.channel,
            status=conversation.status,
            escalated=conversation.escalated,
            escalation_reason=conversation.escalation_reason,
            escalated_at=_iso(conversation.escalated_at),
            assigned_to=conversation.assigned_to,
            assigned_at=_iso(conversation.assigned_at),
            ticket_id=conversation.ticket_id,
            last_intent=conversation.last_intent,
            last_message=self.repository.last_message_text(conversation.conversation_id),
            last_message_at=_iso(conversation.last_message_at),
            message_count=conversation.message_count or 0,
            resolved_at=_iso(conversation.resolved_at),
            resolved_by=conversation.resolved_by,
            created_at=_iso(conversation.created_at),
        )


def _message_response(message: ConversationMessage) -> MessageResponse:
    return MessageResponse(
        id=str(message.id),
        sender_role=message.sender_role,
        agent_id=message.agent_id,
        text=message.text,
        intent=message.intent,
        confidence=message.confidence,
        metadata=message.message_metadata or {},
        created_at=_iso(message.created_at),
    )
