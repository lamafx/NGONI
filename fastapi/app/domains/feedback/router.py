from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from .schemas import (
    FeedbackCreateRequest,
    FeedbackResponse,
    ResponseRatingCreateRequest,
    ResponseRatingResponse,
)
from .service import FeedbackService, ResponseRatingService

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse)
def create_feedback(payload: FeedbackCreateRequest, db: Session = Depends(get_db)):
    service = FeedbackService.from_session(db)
    try:
        return service.create_entry(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=List[FeedbackResponse])
def list_feedback(type: str, db: Session = Depends(get_db)):
    return FeedbackService.from_session(db).list_entries(type)


# Route distincte de "" (pas "/{type}") : une notation est structurellement
# differente d'un FeedbackEntry (question/answer/is_useful, pas un simple
# message), voir ResponseRating (models.py) pour la justification.
@router.post("/ratings", response_model=ResponseRatingResponse)
def create_rating(payload: ResponseRatingCreateRequest, db: Session = Depends(get_db)):
    service = ResponseRatingService.from_session(db)
    try:
        return service.create_rating(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ratings", response_model=List[ResponseRatingResponse])
def list_ratings(
    interaction_type: Optional[str] = None,
    is_useful: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    return ResponseRatingService.from_session(db).list_ratings(interaction_type=interaction_type, is_useful=is_useful)
