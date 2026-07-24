from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FeedbackEntry, ResponseRating
from .schemas import FeedbackCreateRequest, ResponseRatingCreateRequest


class FeedbackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: FeedbackCreateRequest) -> FeedbackEntry:
        entry = FeedbackEntry(
            type=payload.type,
            message=payload.message,
            user_id=payload.user_id,
            created_by=payload.created_by,
        )
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def set_ticket_id(self, entry_id, ticket_id: str) -> None:
        entry = self.session.get(FeedbackEntry, entry_id)
        if entry is not None:
            entry.ticket_id = ticket_id
            self.session.commit()

    def list_by_type(self, feedback_type: str) -> List[FeedbackEntry]:
        stmt = (
            select(FeedbackEntry)
            .where(FeedbackEntry.type == feedback_type)
            .order_by(FeedbackEntry.created_at.desc())
        )
        return self.session.execute(stmt).scalars().all()


class ResponseRatingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: ResponseRatingCreateRequest) -> ResponseRating:
        rating = ResponseRating(
            interaction_type=payload.interaction_type,
            question=payload.question,
            answer=payload.answer,
            is_useful=payload.is_useful,
            user_id=payload.user_id,
            created_by=payload.created_by,
        )
        self.session.add(rating)
        self.session.commit()
        self.session.refresh(rating)
        return rating

    def list_ratings(
        self, interaction_type: Optional[str] = None, is_useful: Optional[bool] = None
    ) -> List[ResponseRating]:
        stmt = select(ResponseRating).order_by(ResponseRating.created_at.desc())
        if interaction_type is not None:
            stmt = stmt.where(ResponseRating.interaction_type == interaction_type)
        if is_useful is not None:
            stmt = stmt.where(ResponseRating.is_useful == is_useful)
        return self.session.execute(stmt).scalars().all()
