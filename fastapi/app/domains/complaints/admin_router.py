"""Premiere route admin du moteur (voir docs/13-limitations.md §13.1) --
gestion des tickets (reclamations, escalades diagnostic/feedback) par
l'equipe support. Tout le routeur est protege par require_admin_auth
(header X-Internal-Secret), meme convention que le module admin de
ngoni-core-service (fastify.addHook('preHandler', assertInternalAuth))."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.shared.admin_auth import get_admin_id, require_admin_auth

from .schemas import AdminComplaintStatusUpdateRequest, ComplaintResponse
from .service import ComplaintService

router = APIRouter(
    prefix="/admin/complaints",
    tags=["admin"],
    dependencies=[Depends(require_admin_auth)],
)


@router.get("/", response_model=List[ComplaintResponse])
def list_complaints(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    urgency: Optional[str] = Query(None),
    created_by: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = ComplaintService.from_session(db)
    return service.list_tickets(
        status=status, category=category, urgency=urgency, created_by=created_by,
        limit=limit, offset=offset,
    )


@router.get("/{ticket_id}", response_model=ComplaintResponse)
def get_complaint_admin(ticket_id: str, db: Session = Depends(get_db)):
    complaint = ComplaintService.from_session(db).get_ticket(ticket_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Réclamation introuvable")
    return complaint


@router.patch("/{ticket_id}", response_model=ComplaintResponse)
def update_complaint_status(
    ticket_id: str,
    payload: AdminComplaintStatusUpdateRequest,
    admin_id: Optional[str] = Depends(get_admin_id),
    db: Session = Depends(get_db),
):
    service = ComplaintService.from_session(db)
    try:
        updated = service.update_status(ticket_id, payload.status, updated_by=admin_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Réclamation introuvable")
    return updated
