from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SupportUserResponse(BaseModel):
    """Un usager tel que le support le connait. Pas de nom ni d'email : ces
    donnees appartiennent a ngoni-user-service (voir service.py), ce domaine
    ne les invente pas."""

    user_id: str
    conversations: int = 0
    escalations: int = 0
    tickets: int = 0
    open_tickets: int = 0
    last_activity: Optional[str] = None


class SupportUserDetailResponse(SupportUserResponse):
    messages_sent: int = 0
    conversation_list: List[Dict[str, Any]] = Field(default_factory=list)
    ticket_list: List[Dict[str, Any]] = Field(default_factory=list)
