import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.domains.conversations.service import ConversationService
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from domains.conversations.service import ConversationService
from .schemas import ComplaintResponse, TicketCreateRequest, TicketCreateResponse
from .service import ComplaintService

logger = logging.getLogger(__name__)

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
        created = service.create_ticket(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Un ticket cree DEPUIS une conversation est, par definition, un sujet
    # que l'assistant n'a pas su clore seul : la conversation rejoint la file
    # des conseillers. C'est fait ici, cote serveur, et non dans les actions
    # Rasa -- les trois chemins de creation de ticket (formulaire de
    # reclamation, escalade diagnostic, suivi de feedback) passent tous par
    # cette route, un seul point d'accrochage couvre donc les trois sans
    # toucher au moteur de dialogue.
    #
    # Best-effort : le ticket est deja cree et confirme a l'utilisateur, une
    # panne de cette mise en file ne doit jamais transformer ca en erreur.
    if payload.user_id:
        try:
            ConversationService.from_session(db).escalate(
                payload.user_id,
                reason=f"ticket_{payload.created_by}",
                ticket_id=created.ticket_id,
                user_id=payload.user_id,
            )
        except Exception as error:  # pragma: no cover - jamais bloquant
            logger.warning(
                "Ticket %s cree mais mise en file conseiller impossible (%s)",
                created.ticket_id, error,
            )
    return created
