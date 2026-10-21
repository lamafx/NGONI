"""Route de supervision agregee -- meme protection que les autres routes
d'administration (header X-Internal-Secret, voir shared/admin_auth.py) : ces
compteurs exposent le volume d'activite et les questions posees par les
utilisateurs, ce n'est pas une donnee publique."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.shared.admin_auth import require_admin_auth
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from shared.admin_auth import require_admin_auth

from .schemas import StatsOverviewResponse
from .service import DEFAULT_PERIOD_DAYS, StatsService

router = APIRouter(
    prefix="/admin/stats",
    tags=["admin"],
    dependencies=[Depends(require_admin_auth)],
)


@router.get("/overview", response_model=StatsOverviewResponse)
def stats_overview(
    days: int = Query(DEFAULT_PERIOD_DAYS, ge=1, le=365, description="Profondeur des séries temporelles, en jours"),
    db: Session = Depends(get_db),
):
    return StatsService.from_session(db).overview(days=days)
