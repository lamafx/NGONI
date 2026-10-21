"""Surcharges des seuils NLU/FAQ/diagnostic/reclamation depuis l'espace
Admin (voir frontfolder/src/pages/AdminSettingsPage.jsx et
frontfolder/src/data/systemParameters.js pour le registre cote front, cense
rester en phase avec KNOWN_PARAMETERS dans service.py).

Ne stocke QUE les surcharges explicitement ecrites -- jamais les valeurs par
defaut, qui restent les constantes Python/YAML d'origine (rasa/config.yml,
fastapi/app/domains/faq/service.py, rasa/actions/diagnostic.py, rasa/actions/
reclamation.py, fastapi/app/domains/diagnostic/adapter.py). Voir
migrations/0015_system_parameters.sql pour le schema exact et le rappel
important : Rasa/FastAPI ne relisent pas encore cette table a chaud."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, String
from sqlalchemy.dialects.postgresql import UUID

try:
    from app.models import Base
except ImportError:  # pragma: no cover - support running as `main`
    from models import Base


class SystemParameter(Base):
    __tablename__ = "system_parameters"
    __table_args__ = {"schema": "ia"}

    param_id = Column(String, primary_key=True)
    value = Column(Float, nullable=False)
    updated_by = Column(String, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SystemParameterHistory(Base):
    __tablename__ = "system_parameter_history"
    __table_args__ = {"schema": "ia"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    param_id = Column(String, nullable=False)
    old_value = Column(Float, nullable=True)
    new_value = Column(Float, nullable=False)
    # Tracabilite obligatoire (nom + prenom saisis via TraceabilityModal,
    # AdminSettingsPage.jsx) -- jamais NULL, contrairement a
    # complaints.updated_by qui reste optionnel.
    changed_by = Column(String, nullable=False)
    changed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
