from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import SystemParameter, SystemParameterHistory


class SystemParameterRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, param_id: str) -> Optional[SystemParameter]:
        return self.session.get(SystemParameter, param_id)

    def list_all(self) -> List[SystemParameter]:
        stmt = select(SystemParameter).order_by(SystemParameter.param_id)
        return self.session.execute(stmt).scalars().all()

    def upsert(self, param_id: str, value: float, updated_by: str) -> SystemParameter:
        existing = self.get(param_id)
        if existing is None:
            existing = SystemParameter(param_id=param_id, value=value, updated_by=updated_by)
            self.session.add(existing)
        else:
            existing.value = value
            existing.updated_by = updated_by
        self.session.commit()
        self.session.refresh(existing)
        return existing

    def add_history(
        self, param_id: str, old_value: Optional[float], new_value: float, changed_by: str
    ) -> SystemParameterHistory:
        entry = SystemParameterHistory(
            param_id=param_id, old_value=old_value, new_value=new_value, changed_by=changed_by
        )
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def clear_history(self, param_id: Optional[str] = None) -> int:
        """Purge le journal des modifications, et lui seul : les valeurs
        courantes (system_parameters) ne sont pas touchees. Effacer une trace
        n'annule pas le reglage qu'elle documente -- confondre les deux
        remettrait silencieusement des seuils a leur valeur par defaut.

        Renvoie le nombre de lignes supprimees."""
        stmt = delete(SystemParameterHistory)
        if param_id is not None:
            stmt = stmt.where(SystemParameterHistory.param_id == param_id)
        result = self.session.execute(stmt)
        self.session.commit()
        return int(result.rowcount or 0)

    def list_history(self, param_id: Optional[str] = None, limit: int = 100) -> List[SystemParameterHistory]:
        stmt = select(SystemParameterHistory).order_by(SystemParameterHistory.changed_at.desc()).limit(limit)
        if param_id is not None:
            stmt = stmt.where(SystemParameterHistory.param_id == param_id)
        return self.session.execute(stmt).scalars().all()
