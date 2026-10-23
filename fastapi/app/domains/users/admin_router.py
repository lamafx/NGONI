"""Usagers vus par le support (voir api_admin_a_developper.md section 6).

Agregation en lecture seule sur les tables du schema `ia` -- aucune table
d'utilisateurs n'est creee ici, volontairement : les profils appartiennent a
ngoni-user-service (voir service.py pour le raisonnement complet)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.shared.admin_auth import require_admin_role
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from shared.admin_auth import require_admin_role

from .schemas import SupportUserDetailResponse, SupportUserResponse
from .service import UserService

router = APIRouter(
    prefix="/admin/users",
    tags=["admin"],
    dependencies=[Depends(require_admin_role)],
)


@router.get("/", response_model=List[SupportUserResponse])
def list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return UserService.from_session(db).list_users(limit=limit, offset=offset)


@router.get("/{user_id}", response_model=SupportUserDetailResponse)
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = UserService.from_session(db).get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usager inconnu du support")
    return user
