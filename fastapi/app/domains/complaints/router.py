from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

try:
    from app.database import get_db
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
from .schemas import ComplaintResponse, TicketCreateRequest, TicketCreateResponse
from .service import ComplaintService

router = APIRouter(prefix='/complaints', tags=['complaints'])


# Enregistree AVANT '/{ticket_id}' ci-dessous : sinon Starlette matcherait
# "/complaints/mine" contre la route parametree ("mine" pris pour un
# ticket_id), l'ordre d'enregistrement fait foi pour les routes en
# concurrence.
@router.get('/mine', response_model=List[ComplaintResponse])
def list_my_complaints(
    x_user_id: str = Header(..., alias='X-User-ID'),
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return ComplaintService.from_session(db).list_tickets(
        user_id=x_user_id, status=status, limit=limit, offset=offset,
    )


@router.get('/{ticket_id}', response_model=ComplaintResponse)
def get_complaint(ticket_id: str, x_user_id: str = Header(..., alias='X-User-ID'), db: Session = Depends(get_db)):
    complaint = ComplaintService.from_session(db).get_ticket(ticket_id)
    # 404 (pas 403) si le ticket appartient a un autre utilisateur : ne
    # confirme pas a un appelant non proprietaire qu'un ticket_id donne
    # existe reellement (audit securite -- endpoint auparavant sans aucun
    # controle d'acces, confirme sans consommateur existant avant ce fix).
    if complaint is None or complaint.user_id != x_user_id:
        raise HTTPException(status_code=404, detail='Réclamation introuvable')
    return complaint


@router.post('/create', response_model=TicketCreateResponse)
def create_ticket(payload: TicketCreateRequest, db: Session = Depends(get_db)):
    service = ComplaintService.from_session(db)
    try:
        return service.create_ticket(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
