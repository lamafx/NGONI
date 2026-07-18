from typing import Optional

from pydantic import BaseModel

DEFAULT_CREATED_BY = "ai_agent"


class FeedbackCreateRequest(BaseModel):
    type: str
    message: str
    user_id: Optional[str] = None
    created_by: str = DEFAULT_CREATED_BY


class FeedbackResponse(BaseModel):
    id: str
    type: str
    message: str
    user_id: Optional[str] = None
    created_by: str
    created_at: Optional[str] = None
    # Renseigne uniquement pour suggestion/complaint_sentiment (voir
    # FeedbackService._create_ticket_for_entry) -- None si le type ne cree
    # pas de ticket, ou si la creation du ticket a echoue (best-effort).
    ticket_id: Optional[str] = None


class ResponseRatingCreateRequest(BaseModel):
    interaction_type: str
    question: str
    answer: str
    is_useful: bool
    user_id: Optional[str] = None
    created_by: str = DEFAULT_CREATED_BY


class ResponseRatingResponse(BaseModel):
    id: str
    interaction_type: str
    question: str
    answer: str
    is_useful: bool
    user_id: Optional[str] = None
    created_by: str
    created_at: Optional[str] = None
