import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models import Base


class Complaint(Base):
    __tablename__ = "complaints"
    __table_args__ = {"schema": "complaints"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(String, nullable=False, unique=True)
    # Texte libre plutot que UUID : l'identite appelante (tracker.sender_id
    # cote Rasa, X-User-ID cote Engine) n'est pas toujours un UUID valide
    # (ex. "frontend_user" pour la page /chat sans utilisateur reel).
    user_id = Column(String, nullable=True)
    category = Column(String, nullable=False)
    description = Column(String, nullable=False)
    summary = Column(String, nullable=True)
    urgency = Column(String, nullable=False, default="medium")
    status = Column(String, nullable=False, default="OPEN")
    order_number = Column(String, nullable=True)
    incident_date = Column(String, nullable=True)
    department = Column(String, nullable=True)
    additional_info = Column(String, nullable=True)
    context = Column(JSONB, nullable=True)
    # Tracabilite : voir init_db.sql pour les valeurs possibles.
    created_by = Column(String, nullable=False)
    # Dedoublonnage cote serveur (migrations/0009) : une relance reseau (ex.
    # timeout apres un commit reussi mais reponse perdue) reutilise la meme
    # cle plutot que de creer un second ticket -- voir
    # ComplaintService.create_ticket. Nullable : les appelants qui n'en
    # fournissent pas (anciens clients, appels API directs) ne sont pas
    # affectes, une contrainte UNIQUE Postgres autorisant plusieurs NULL.
    idempotency_key = Column(String, nullable=True, unique=True)
    # Identite de l'admin ayant modifie ce ticket en dernier (X-User-ID, voir
    # app/shared/admin_auth.py::get_admin_id et admin_router.py) -- None tant
    # qu'aucun admin n'a jamais touche le ticket depuis sa creation.
    updated_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
