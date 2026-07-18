from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from .schemas import ComplaintResponse, TicketCreateRequest, TicketCreateResponse
from .service import ComplaintService

router = APIRouter(prefix='/complaints', tags=['complaints'])


@router.get('/{ticket_id}', response_model=ComplaintResponse)
def get_complaint(ticket_id: str, db: Session = Depends(get_db)):
    complaint = ComplaintService.from_session(db).get_ticket(ticket_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail='Réclamation introuvable')
    return complaint


@router.post('/create', response_model=TicketCreateResponse)
def create_ticket(payload: TicketCreateRequest, db: Session = Depends(get_db)):
    service = ComplaintService.from_session(db)
    try:
        return service.create_ticket(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
