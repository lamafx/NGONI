from typing import Optional

from pydantic import BaseModel, Field


class AgentResponse(BaseModel):
    agent_id: str
    display_name: str
    role: str
    # Statut DECLARE (champ en base) et statut EFFECTIF (derive de
    # last_seen_at) : un conseiller qui s'est declare "en ligne" lundi et n'a
    # rien fait depuis n'est pas en ligne. L'interface affiche `status`, mais
    # les deux sont renvoyes pour que l'ecart reste lisible.
    declared_status: str
    status: str
    last_seen_at: Optional[str] = None
    # Charge reelle, comptee en base au moment de la lecture.
    active_conversations: int = 0
    assigned_tickets: int = 0
    created_at: Optional[str] = None


class AgentCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    agent_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="conseiller", max_length=100)


class AgentStatusUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    status: str
