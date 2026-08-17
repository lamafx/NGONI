from fastapi import APIRouter

from .engines import DEFAULT_ENGINE, list_engines
from .schemas import NluEngineSummary, NluEnginesResponse

router = APIRouter(prefix="/api", tags=["nlu"])


@router.get("/models", response_model=NluEnginesResponse)
def get_models() -> NluEnginesResponse:
    """Catalogue des moteurs NLU disponibles, pour peupler le selecteur de
    modele cote frontend (voir frontend/pages/chat/model.store.js) --
    ajouter un moteur dans engines.ENGINES le fait apparaitre ici sans
    modification du frontend."""
    return NluEnginesResponse(
        models=[NluEngineSummary(id=spec.id, label=spec.label) for spec in list_engines()],
        default=DEFAULT_ENGINE,
    )
