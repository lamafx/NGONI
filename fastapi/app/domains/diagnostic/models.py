"""Modeles SQLAlchemy pour la tracabilite du Diagnostic Engine (Phase 6,
etape 26, voir docs/diagnostic-roadmap.md) -- meme convention que
app.domains.complaints.models (schema Postgres dedie, UUID en cle primaire
pour le log, colonnes JSONB pour le contexte).

Deux tables, deux granularites :
  - DiagnosticSession : UNE ligne par session_id, mise a jour a chaque tour
    (etat courant -- utile pour "ou en est cette conversation ?").
  - DiagnosticAuditLog : UNE ligne par appel a /diagnostic/resolve (historique
    complet, jamais mis a jour -- utile pour rejouer/auditer une session
    apres coup, ou pour les captures d'ecran du memoire).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models import Base


class DiagnosticSession(Base):
    __tablename__ = "diagnostic_sessions"
    __table_args__ = {"schema": "ia"}

    # session_id (pas un UUID genere ici) : c'est le meme identifiant que
    # Rasa utilise cote conversation (tracker.sender_id / session_id du
    # contrat client-request.schema.json) -- cle naturelle, pas de UUID
    # supplementaire a faire correspondre.
    session_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=True)
    service = Column(String, nullable=True)
    problem = Column(String, nullable=True)
    # IN_PROGRESS | RESOLVED | ESCALATED -- derive de outcome.outcome a
    # chaque tour (voir audit_repository.py), jamais defini ailleurs pour
    # eviter deux sources de verite sur le meme statut.
    status = Column(String, nullable=False, default="IN_PROGRESS")
    last_outcome = Column(String, nullable=True)
    turns_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DiagnosticAuditLog(Base):
    __tablename__ = "diagnostic_audit_log"
    __table_args__ = {"schema": "ia"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    service = Column(String, nullable=False)
    problem = Column(String, nullable=False)
    called_endpoint = Column(String, nullable=True)
    request_entities = Column(JSONB, nullable=True)
    # RESOLVED | ESCALATE | NEED_MORE_INFO -- meme valeur que le champ
    # `outcome` discriminant de contracts.DiagnosticInvocationResponse.
    outcome = Column(String, nullable=False)
    # resolution_code (RESOLVED), escalation_reason (ESCALATE), ou
    # missing_fields joints par une virgule (NEED_MORE_INFO) -- toujours une
    # simple chaine, jamais reinterprete cote SQL, uniquement pour lecture
    # humaine (audit, memoire).
    outcome_detail = Column(String, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    # Renseigne a posteriori par link_latest_escalation() (audit_repository.py)
    # quand une escalade SERVICE_UNAVAILABLE aboutit a un ticket automatique
    # -- absent au moment de l'ecriture initiale (record()), le ticket
    # n'existe qu'apres le retour de pipeline.resolve() (voir router.py).
    related_ticket_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
