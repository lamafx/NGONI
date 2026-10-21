from typing import Optional

from pydantic import BaseModel


class SystemParameterUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    value: float
    # Nom complet saisi via la modale de tracabilite (AdminSettingsPage.jsx)
    # -- jamais deduit d'un en-tete non verifie (X-User-ID reste disponible
    # separement pour l'admin technique, voir get_admin_id) : c'est
    # l'identite EXPLICITEMENT saisie par la personne qui modifie le seuil
    # qui doit apparaitre dans l'historique.
    changed_by: str


class SystemParameterResponse(BaseModel):
    param_id: str
    value: float
    updated_by: str
    updated_at: Optional[str] = None


class SystemParameterHistoryResponse(BaseModel):
    id: str
    param_id: str
    old_value: Optional[float] = None
    new_value: float
    changed_by: str
    changed_at: Optional[str] = None
