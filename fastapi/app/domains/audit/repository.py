from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentAction
from .schemas import AgentActionCreateRequest


class AgentActionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, payload: AgentActionCreateRequest) -> AgentAction:
        action = AgentAction(
            trace_id=payload.trace_id,
            session_id=payload.session_id,
            user_id=payload.user_id,
            domain=payload.domain,
            action_type=payload.action_type,
            input_data=payload.input_data,
            output_data=payload.output_data,
            related_ticket_id=payload.related_ticket_id,
        )
        self.session.add(action)
        self.session.commit()
        self.session.refresh(action)
        return action

    def list_actions(
        self,
        domain: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[AgentAction]:
        stmt = select(AgentAction).order_by(AgentAction.created_at.desc()).limit(limit)
        if domain is not None:
            stmt = stmt.where(AgentAction.domain == domain)
        if session_id is not None:
            stmt = stmt.where(AgentAction.session_id == session_id)
        return self.session.execute(stmt).scalars().all()
