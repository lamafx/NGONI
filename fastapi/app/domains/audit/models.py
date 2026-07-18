"""Trace generique des decisions autonomes du systeme non deja couvertes par
un audit specifique a un domaine (voir app.domains.diagnostic.audit_repository
pour /diagnostic/resolve, qui reste inchange). Ce domaine couvre notamment :
- les reponses FAQ servies (app/domains/faq/router.py, app/main.py) ;
- la classification d'un probleme diagnostique, decidee cote serveur
  d'actions Rasa (process externe sans acces direct a la base -- voir
  router.py de ce domaine et rasa/actions/diagnostic.py::_report_agent_action).

Best-effort partout : une panne d'ecriture ici ne doit jamais faire echouer
une reponse deja donnee a l'utilisateur, meme principe que
app.domains.diagnostic.audit_repository."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models import Base


class AgentAction(Base):
    __tablename__ = "agent_actions"
    __table_args__ = {"schema": "audit"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Absent pour les actions sans notion de trace_id (ex. reponse FAQ) --
    # seule la classification diagnostic en porte un aujourd'hui (correle a
    # diagnostic.diagnostic_audit_log.trace_id, cote /diagnostic/resolve).
    trace_id = Column(String, nullable=True)
    session_id = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    # 'faq' | 'diagnostic_classification' -- voir service.py::ALLOWED_DOMAINS.
    # TEXT + validation applicative (pas un ENUM Postgres) : meme convention
    # que complaints.created_by / feedback.entries.type, une nouvelle valeur
    # ne doit jamais exiger de migration de type.
    domain = Column(String, nullable=False)
    action_type = Column(String, nullable=False)
    input_data = Column(JSONB, nullable=True)
    output_data = Column(JSONB, nullable=True)
    # Renseigne a posteriori (voir diagnostic/router.py et feedback/service.py)
    # quand une escalade/un feedback aboutit a un ticket de suivi -- jamais
    # garanti par une contrainte de cle etrangere (cf. 15.1 de la doc :
    # aucune FK inter-schema dans ce projet).
    related_ticket_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
