from typing import Optional
from pydantic import BaseModel, Field

# Valeurs attendues pour created_by -- voir init_db.sql et
# app/domains/complaints/models.py pour le detail de chacune. Champ texte
# libre (pas un Literal strict) pour ne pas casser un futur appelant qui
# introduirait une nouvelle origine sans devoir toucher ce fichier.
DEFAULT_CREATED_BY = "user_reclamation_form"

# Cycle de vie d'un ticket (voir migrations/0008_complaints_status_lifecycle.sql,
# meme contrainte cote base) : OPEN (nouveau) -> IN_PROGRESS (pris en charge)
# -> RESOLVED / CLOSED. Pas de machine a etats stricte imposee ici (ex. OPEN
# -> CLOSED directement reste autorise, cas frequent d'un doublon) -- seule
# l'appartenance a cet ensemble est verifiee.
ALLOWED_STATUSES = {"OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"}


class ComplaintResponse(BaseModel):
    ticket_id: str
    user_id: Optional[str] = None
    category: str
    description: str
    summary: Optional[str] = None
    urgency: str
    status: str
    order_number: Optional[str] = None
    incident_date: Optional[str] = None
    department: Optional[str] = None
    additional_info: Optional[str] = None
    context: dict = Field(default_factory=dict)
    created_by: str
    updated_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminComplaintStatusUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    status: str


class TicketCreateRequest(BaseModel):
    category: str
    description: str
    urgency: Optional[str] = "medium"
    incident_date: Optional[str] = None
    summary: Optional[str] = None
    confirmation: Optional[str] = None
    # Contexte libre (service/probleme/entities du diagnostic qui a mene a
    # cette escalade, par exemple) -- voir docs/diagnostic-roadmap.md Phase 3,
    # etape 17. Jamais interprete, uniquement trace pour l'equipe support.
    context: dict = Field(default_factory=dict)
    # Tracabilite (voir init_db.sql) : qui/quoi a initie ce ticket. Toujours
    # renseigne explicitement par l'appelant en pratique (Rasa ou l'Engine) ;
    # la valeur par defaut ne couvre que d'eventuels appels directs de l'API.
    user_id: Optional[str] = None
    created_by: str = DEFAULT_CREATED_BY


class TicketCreateResponse(BaseModel):
    ticket_id: str
    status: str
    message: str
