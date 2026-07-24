from typing import List, Optional

from sqlalchemy.orm import Session

from .models import Complaint
from .schemas import TicketCreateRequest


class ComplaintRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_ticket(self, ticket_id: str, payload: TicketCreateRequest) -> Complaint:
        complaint = Complaint(
            ticket_id=ticket_id,
            user_id=payload.user_id,
            category=payload.category,
            description=payload.description,
            summary=payload.summary,
            urgency=payload.urgency or "medium",
            status="OPEN",
            incident_date=payload.incident_date,
            context=payload.context,
            created_by=payload.created_by,
            idempotency_key=payload.idempotency_key,
        )
        self.session.add(complaint)
        self.session.commit()
        self.session.refresh(complaint)
        return complaint

    def get_by_ticket_id(self, ticket_id: str) -> Complaint | None:
        return self.session.query(Complaint).filter_by(ticket_id=ticket_id).first()

    def get_by_idempotency_key(self, idempotency_key: str) -> Complaint | None:
        return self.session.query(Complaint).filter_by(idempotency_key=idempotency_key).first()

    def list_tickets(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        urgency: Optional[str] = None,
        created_by: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Complaint]:
        query = self.session.query(Complaint)
        if status is not None:
            query = query.filter(Complaint.status == status)
        if category is not None:
            query = query.filter(Complaint.category == category)
        if urgency is not None:
            query = query.filter(Complaint.urgency == urgency)
        if created_by is not None:
            query = query.filter(Complaint.created_by == created_by)
        if user_id is not None:
            query = query.filter(Complaint.user_id == user_id)
        return (
            query.order_by(Complaint.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def update_status(self, ticket_id: str, status: str, updated_by: Optional[str]) -> Complaint | None:
        complaint = self.get_by_ticket_id(ticket_id)
        if complaint is None:
            return None
        complaint.status = status
        complaint.updated_by = updated_by
        # updated_at n'est jamais assigne explicitement ici : la colonne porte
        # deja onupdate=... (voir models.py), declenche automatiquement des
        # que la ligne change reellement lors du commit ci-dessous.
        self.session.commit()
        self.session.refresh(complaint)
        return complaint
