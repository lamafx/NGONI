import logging
from typing import List, Optional

from sqlalchemy.orm import Session

try:
    from app.domains.complaints.schemas import TicketCreateRequest
    from app.domains.complaints.service import ComplaintService
except ImportError:  # pragma: no cover - support running as `main`
    from domains.complaints.schemas import TicketCreateRequest
    from domains.complaints.service import ComplaintService

from .models import FeedbackEntry, FeedbackType, RatingInteractionType, ResponseRating
from .repository import FeedbackRepository, ResponseRatingRepository
from .schemas import (
    FeedbackCreateRequest,
    FeedbackResponse,
    ResponseRatingCreateRequest,
    ResponseRatingResponse,
)

logger = logging.getLogger(__name__)

# Longueur max alignee sur MAX_DESCRIPTION_LENGTH (rasa/actions/reclamation.py) :
# meme raisonnement, protection contre l'epuisement de ressources sur un champ
# libre sans autre limite.
MAX_MESSAGE_LENGTH = 2000

# Suggestion et plainte (complaint_sentiment) creent chacune, en plus de leur
# entree feedback.entries (trace brute du message), un ticket de suivi dans
# complaints.complaints -- pour que chaque signal reste actionnable par
# l'equipe support, pas seulement consultable en base. `created_by` dedie
# ('ai_feedback_ticket', voir migrations/0005) pour distinguer cette origine
# de celles deja existantes (formulaire de reclamation, escalade de
# diagnostic).
FEEDBACK_TICKET_CATEGORY = {
    FeedbackType.SUGGESTION.value: "Suggestion",
    FeedbackType.COMPLAINT_SENTIMENT.value: "Plainte",
}
FEEDBACK_TICKET_URGENCY = {
    FeedbackType.SUGGESTION.value: "low",
    FeedbackType.COMPLAINT_SENTIMENT.value: "medium",
}
FEEDBACK_TICKET_CREATED_BY = "ai_feedback_ticket"


class FeedbackService:
    def __init__(
        self,
        repository: Optional[FeedbackRepository] = None,
        complaint_service: Optional[ComplaintService] = None,
    ) -> None:
        self.repository = repository
        self.complaint_service = complaint_service

    def create_entry(self, payload: FeedbackCreateRequest) -> FeedbackResponse:
        if payload.type not in {t.value for t in FeedbackType}:
            raise ValueError(f"Type de feedback inconnu : {payload.type!r}")
        message = payload.message.strip()
        if not message:
            raise ValueError("Le message ne peut pas être vide")
        payload = payload.model_copy(update={"message": message[:MAX_MESSAGE_LENGTH]})

        if self.repository is None:
            raise RuntimeError("FeedbackService requiert un repository pour persister une entree")
        entry = self.repository.create(payload)
        # Capture immediate en valeurs Python simples, AVANT tout appel DB
        # supplementaire (creation de ticket ci-dessous) : un flush en echec
        # (ex. contrainte CHECK violee cote complaints, deja vu en pratique)
        # laisse la Session partagee (meme session que ComplaintService, voir
        # from_session()) dans un etat "pending rollback" -- toute relecture
        # d'attribut ORM sur `entry` APRES coup (y compris dans le except
        # ci-dessous, ou pour construire la reponse) echouerait alors avec
        # sqlalchemy.exc.PendingRollbackError, transformant un echec deja
        # gere en 500 brut plutot qu'une reponse degradee normale.
        entry_id = entry.id
        entry_type = entry.type
        entry_message = entry.message
        entry_user_id = entry.user_id
        entry_created_by = entry.created_by
        entry_created_at = entry.created_at
        ticket_id = self._create_ticket_for_entry(entry_id, entry_type, entry_message, entry_user_id)
        return FeedbackResponse(
            id=str(entry_id) if entry_id else "",
            type=entry_type,
            message=entry_message,
            user_id=entry_user_id,
            created_by=entry_created_by,
            created_at=entry_created_at.isoformat() if entry_created_at else None,
            ticket_id=ticket_id,
        )

    def _create_ticket_for_entry(
        self, entry_id, entry_type: str, entry_message: str, entry_user_id: Optional[str]
    ) -> Optional[str]:
        category = FEEDBACK_TICKET_CATEGORY.get(entry_type)
        if category is None or self.complaint_service is None:
            return None
        request = TicketCreateRequest(
            category=category,
            description=entry_message,
            urgency=FEEDBACK_TICKET_URGENCY.get(entry_type, "low"),
            summary=f"[{category}] {entry_message[:150]}",
            # Ticket cree automatiquement des la reception du feedback, sans
            # etape de confirmation dediee -- meme raisonnement que
            # app/domains/diagnostic/escalation.py pour l'escalade auto.
            confirmation="oui",
            user_id=entry_user_id,
            created_by=FEEDBACK_TICKET_CREATED_BY,
        )
        try:
            ticket_id = self.complaint_service.create_ticket(request).ticket_id
            if self.repository is not None:
                try:
                    self.repository.set_ticket_id(entry_id, ticket_id)
                except Exception:
                    # Meme principe que plus bas : le ticket existe deja et
                    # sera bien renvoye dans la reponse API -- seule la
                    # persistance du lien en base echoue ici, pas
                    # l'operation elle-meme.
                    logger.warning("Echec de la persistance du lien ticket pour le feedback %s", entry_id, exc_info=True)
            return ticket_id
        except Exception:
            # Best-effort : l'entree feedback est deja persistee ci-dessus --
            # un echec de creation de ticket ne doit jamais faire echouer la
            # reponse utilisateur, meme principe que l'ecriture d'audit du
            # Diagnostic Engine (pipeline.py). entry_id (valeur simple deja
            # capturee par l'appelant, voir create_entry) plutot que
            # entry.id : voir le commentaire ci-dessus sur PendingRollbackError.
            logger.exception("Echec de creation du ticket de suivi pour le feedback %s", entry_id)
            return None

    def list_entries(self, feedback_type: str) -> List[FeedbackResponse]:
        if self.repository is None:
            return []
        entries = self.repository.list_by_type(feedback_type)
        return [_to_response(entry) for entry in entries]

    @classmethod
    def from_session(cls, session: Session) -> "FeedbackService":
        return cls(FeedbackRepository(session), ComplaintService.from_session(session))


def _to_response(entry: FeedbackEntry, ticket_id: Optional[str] = None) -> FeedbackResponse:
    return FeedbackResponse(
        id=str(entry.id) if entry.id else "",
        type=entry.type,
        message=entry.message,
        user_id=entry.user_id,
        created_by=entry.created_by,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
        ticket_id=ticket_id,
    )


class ResponseRatingService:
    def __init__(self, repository: Optional[ResponseRatingRepository] = None) -> None:
        self.repository = repository

    def create_rating(self, payload: ResponseRatingCreateRequest) -> ResponseRatingResponse:
        if payload.interaction_type not in {t.value for t in RatingInteractionType}:
            raise ValueError(f"Type d'interaction inconnu : {payload.interaction_type!r}")
        if not payload.question.strip() or not payload.answer.strip():
            raise ValueError("question et answer ne peuvent pas être vides")
        payload = payload.model_copy(
            update={
                "question": payload.question.strip()[:MAX_MESSAGE_LENGTH],
                "answer": payload.answer.strip()[:MAX_MESSAGE_LENGTH],
            }
        )

        if self.repository is None:
            raise RuntimeError("ResponseRatingService requiert un repository pour persister une notation")
        rating = self.repository.create(payload)
        return _rating_to_response(rating)

    def list_ratings(self, interaction_type: Optional[str] = None, is_useful: Optional[bool] = None) -> List[ResponseRatingResponse]:
        if self.repository is None:
            return []
        ratings = self.repository.list_ratings(interaction_type=interaction_type, is_useful=is_useful)
        return [_rating_to_response(rating) for rating in ratings]

    @classmethod
    def from_session(cls, session: Session) -> "ResponseRatingService":
        return cls(ResponseRatingRepository(session))


def _rating_to_response(rating: ResponseRating) -> ResponseRatingResponse:
    return ResponseRatingResponse(
        id=str(rating.id) if rating.id else "",
        interaction_type=rating.interaction_type,
        question=rating.question,
        answer=rating.answer,
        is_useful=rating.is_useful,
        user_id=rating.user_id,
        created_by=rating.created_by,
        created_at=rating.created_at.isoformat() if rating.created_at else None,
    )
