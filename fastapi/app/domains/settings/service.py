from typing import List, Optional

from sqlalchemy.orm import Session

from .models import SystemParameter, SystemParameterHistory
from .repository import SystemParameterRepository
from .schemas import SystemParameterHistoryResponse, SystemParameterResponse

# Identifiants et bornes valides -- DOIT rester en phase avec
# frontfolder/src/data/systemParameters.js (memes `id`, memes ordres de
# grandeur). Une liste blanche fermee (et non une simple validation de type)
# : ecrire un param_id inconnu depuis l'admin ne doit jamais silencieusement
# creer une ligne orpheline que rien ne relit jamais cote moteur.
#
# (min, max) -- les seuils de similarite/confiance ("pct" cote front) sont
# des fractions 0-1 ; les autres sont des comptages/delais, bornes larges
# pour rester permissif sans autoriser une valeur absurde (ex. 0 requete/min).
KNOWN_PARAMETERS = {
    "nlu.confidence_threshold": (0.0, 1.0),
    "nlu.ambiguity_threshold": (0.0, 1.0),
    "faq.default_threshold": (0.0, 1.0),
    "faq.secondary_threshold": (0.0, 1.0),
    "faq.keyword_boost": (0.0, 1.0),
    "diagnostic.min_embedding_similarity": (0.0, 1.0),
    "diagnostic.keyword_rescue_similarity": (0.0, 1.0),
    "reclamation.field_similarity": (0.0, 1.0),
    "reclamation.failure_threshold": (1, 50),
    "reclamation.cooldown_seconds": (0, 3600),
    "diagnostic.circuit_breaker_failure_threshold": (1, 50),
    "diagnostic.circuit_breaker_reset_seconds": (0, 3600),
    "rate_limit.max_requests": (1, 10000),
}


class UnknownParameterError(ValueError):
    pass


class ParameterOutOfRangeError(ValueError):
    pass


class SystemParameterService:
    def __init__(self, repository: Optional[SystemParameterRepository] = None) -> None:
        self.repository = repository

    def list_overrides(self) -> List[SystemParameterResponse]:
        if self.repository is None:
            return []
        return [_to_response(p) for p in self.repository.list_all()]

    def update(self, param_id: str, value: float, changed_by: str) -> SystemParameterResponse:
        if param_id not in KNOWN_PARAMETERS:
            raise UnknownParameterError(f"Paramètre inconnu : {param_id!r}")
        low, high = KNOWN_PARAMETERS[param_id]
        if not (low <= value <= high):
            raise ParameterOutOfRangeError(f"Valeur hors bornes pour {param_id!r} : {value} (attendu entre {low} et {high})")
        if not changed_by.strip():
            raise ValueError("changed_by est requis (traçabilité)")
        if self.repository is None:
            raise RuntimeError("SystemParameterService requiert un repository pour écrire")

        existing = self.repository.get(param_id)
        old_value = existing.value if existing is not None else None
        updated = self.repository.upsert(param_id, value, changed_by.strip())
        self.repository.add_history(param_id, old_value, value, changed_by.strip())
        return _to_response(updated)

    def clear_history(self, param_id: Optional[str] = None) -> int:
        if self.repository is None:
            return 0
        return self.repository.clear_history(param_id=param_id)

    def list_history(self, param_id: Optional[str] = None) -> List[SystemParameterHistoryResponse]:
        if self.repository is None:
            return []
        return [_history_to_response(h) for h in self.repository.list_history(param_id=param_id)]

    @classmethod
    def from_session(cls, session: Session) -> "SystemParameterService":
        return cls(SystemParameterRepository(session))


def _to_response(param: SystemParameter) -> SystemParameterResponse:
    return SystemParameterResponse(
        param_id=param.param_id,
        value=param.value,
        updated_by=param.updated_by,
        updated_at=param.updated_at.isoformat() if param.updated_at else None,
    )


def _history_to_response(entry: SystemParameterHistory) -> SystemParameterHistoryResponse:
    return SystemParameterHistoryResponse(
        id=str(entry.id),
        param_id=entry.param_id,
        old_value=entry.old_value,
        new_value=entry.new_value,
        changed_by=entry.changed_by,
        changed_at=entry.changed_at.isoformat() if entry.changed_at else None,
    )
