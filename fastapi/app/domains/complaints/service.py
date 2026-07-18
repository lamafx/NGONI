import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from .models import Complaint
from .repository import ComplaintRepository
from .schemas import ALLOWED_STATUSES, ComplaintResponse, TicketCreateRequest, TicketCreateResponse


def _generate_ticket_id() -> str:
    # CMP-YYYYMMDD-XXXXXXXX : prefixe date (lisible, triable) + suffixe
    # hexadecimal de 8 caracteres (>4 milliards de combinaisons) -- remplace
    # l'ancien format TCK-XXXX (timestamp % 10000, ~10000 valeurs possibles,
    # boucle toutes les ~2h45 et pouvait entrer en collision).
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:8].upper()
    return f"CMP-{date_part}-{suffix}"


class ComplaintService:
    def __init__(self, repository: ComplaintRepository | None = None) -> None:
        self.repository = repository

    def create_ticket(self, payload: TicketCreateRequest) -> TicketCreateResponse:
        confirmation = (payload.confirmation or "").strip().lower()
        if confirmation not in {"oui", "yes", "o", "y"}:
            raise ValueError("La confirmation utilisateur est obligatoire")
        if not payload.summary:
            raise ValueError("Le résumé est obligatoire")

        ticket_id = _generate_ticket_id()
        if self.repository is not None:
            self.repository.create_ticket(ticket_id, payload)
        return TicketCreateResponse(ticket_id=ticket_id, status="OPEN", message="Ticket créé avec succès")

    def get_ticket(self, ticket_id: str) -> Optional[ComplaintResponse]:
        if self.repository is None:
            return None
        complaint = self.repository.get_by_ticket_id(ticket_id)
        if complaint is None:
            return None
        return _to_response(complaint)

    def list_tickets(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        urgency: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ComplaintResponse]:
        if self.repository is None:
            return []
        complaints = self.repository.list_tickets(
            status=status, category=category, urgency=urgency, created_by=created_by,
            limit=limit, offset=offset,
        )
        return [_to_response(c) for c in complaints]

    def update_status(self, ticket_id: str, status: str, updated_by: Optional[str]) -> Optional[ComplaintResponse]:
        if status not in ALLOWED_STATUSES:
            raise ValueError(
                f"Statut inconnu : {status!r} (attendu : {', '.join(sorted(ALLOWED_STATUSES))})"
            )
        if self.repository is None:
            raise RuntimeError("ComplaintService requiert un repository pour modifier un ticket")
        complaint = self.repository.update_status(ticket_id, status, updated_by)
        if complaint is None:
            return None
        return _to_response(complaint)

    @classmethod
    def from_session(cls, session: Session) -> "ComplaintService":
        return cls(ComplaintRepository(session))


def _to_response(complaint: Complaint) -> ComplaintResponse:
    return ComplaintResponse(
        ticket_id=complaint.ticket_id,
        user_id=complaint.user_id,
        category=complaint.category,
        description=complaint.description,
        summary=complaint.summary,
        urgency=complaint.urgency,
        status=complaint.status,
        order_number=complaint.order_number,
        incident_date=complaint.incident_date,
        department=complaint.department,
        additional_info=complaint.additional_info,
        context=complaint.context or {},
        created_by=complaint.created_by,
        updated_by=complaint.updated_by,
        created_at=complaint.created_at.isoformat() if complaint.created_at else None,
        updated_at=complaint.updated_at.isoformat() if complaint.updated_at else None,
    )
