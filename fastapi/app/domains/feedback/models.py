import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

try:
    from app.models import Base
except ImportError:  # pragma: no cover - support running as `main`
    from models import Base


class FeedbackType(str, enum.Enum):
    SUGGESTION = "suggestion"
    COMPLAINT_SENTIMENT = "complaint_sentiment"


class RatingInteractionType(str, enum.Enum):
    FAQ = "faq"


class FeedbackEntry(Base):
    __tablename__ = "entries"
    __table_args__ = {"schema": "ia"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Texte libre (pas un SAEnum Postgres) : meme raisonnement que
    # complaints.created_by -- une nouvelle valeur de type ne doit jamais
    # exiger une migration de type, seulement une mise a jour de
    # FeedbackType/ALLOWED_TYPES cote application.
    type = Column(String, nullable=False)
    message = Column(String, nullable=False)
    # Texte libre plutot que UUID : meme raison que complaints.user_id
    # (tracker.sender_id cote Rasa n'est pas toujours un UUID valide).
    user_id = Column(String, nullable=True)
    created_by = Column(String, nullable=False, default="ai_agent")
    # Renseigne a posteriori par FeedbackService._create_ticket_for_entry
    # quand ce feedback (suggestion/plainte) cree un ticket de suivi -- voir
    # migrations/0007_ticket_links.sql. Absent au moment de l'insertion
    # initiale (create()), le ticket n'est cree qu'apres.
    ticket_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ResponseRating(Base):
    # Distinct de FeedbackEntry : une suggestion/plainte est un message libre
    # sans rapport avec une reponse precise du bot, alors qu'une notation est
    # TOUJOURS liee a un couple (question, reponse) donne -- d'ou question/
    # answer stockes ici plutot qu'un simple `message`. Permet d'etudier
    # apres coup QUELLES reponses sont jugees utiles ou non, pas seulement un
    # score global.
    __tablename__ = "response_ratings"
    __table_args__ = {"schema": "ia"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Texte libre (meme raisonnement que FeedbackEntry.type) : 'faq'
    # aujourd'hui, extensible a 'diagnostic_resolution' plus tard sans
    # migration de type.
    interaction_type = Column(String, nullable=False)
    question = Column(String, nullable=False)
    answer = Column(String, nullable=False)
    is_useful = Column(Boolean, nullable=False)
    user_id = Column(String, nullable=True)
    created_by = Column(String, nullable=False, default="ai_agent")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
