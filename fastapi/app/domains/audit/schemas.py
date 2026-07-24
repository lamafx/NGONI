from typing import Optional

from pydantic import BaseModel, Field


class AgentActionCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    domain: str
    action_type: str
    input_data: dict = Field(default_factory=dict)
    output_data: dict = Field(default_factory=dict)
    related_ticket_id: Optional[str] = None


class AgentActionResponse(BaseModel):
    id: str
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    domain: str
    action_type: str
    input_data: dict
    output_data: dict
    related_ticket_id: Optional[str] = None
    created_at: Optional[str] = None
