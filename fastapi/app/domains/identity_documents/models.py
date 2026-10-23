"""Pieces d'identite recues dans le chat (table creee par la migration
0017_dossier_client.sql). L'image n'est conservee que pour une piece
ACCEPTEE par le filtre : c'est elle que le conseiller compare au compte."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

try:
    from app.models import Base
except ImportError:  # pragma: no cover - support running as `main`
    from models import Base

REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_NOT_APPLICABLE = "not_applicable"


class IdentityDocument(Base):
    __tablename__ = "identity_documents"
    __table_args__ = {"schema": "ia"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=True)
    conversation_id = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    image = Column(LargeBinary, nullable=True)
    accepted = Column(Boolean, nullable=False)
    document_type = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    fields = Column(JSONB, nullable=False, default=list)
    checks = Column(JSONB, nullable=False, default=list)
    mrz_valid = Column(Boolean, nullable=True)
    kyc_submission_id = Column(UUID(as_uuid=True), nullable=True)
    review_status = Column(String, nullable=False, default=REVIEW_PENDING)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def document_summary(document: IdentityDocument) -> dict:
    """Vue sans l'image (listes, notifications, dossier)."""
    return {
        "document_id": str(document.id),
        "user_id": document.user_id,
        "conversation_id": document.conversation_id,
        "filename": document.filename,
        "content_type": document.content_type,
        "has_image": document.image is not None,
        "accepted": document.accepted,
        "document_type": document.document_type,
        "reason": document.reason,
        "fields": document.fields or [],
        "checks": document.checks or [],
        "mrz_valid": document.mrz_valid,
        "kyc_submission_id": str(document.kyc_submission_id) if document.kyc_submission_id else None,
        "review_status": document.review_status,
        "reviewed_by": document.reviewed_by,
        "reviewed_at": document.reviewed_at.isoformat() if document.reviewed_at else None,
        "review_reason": document.review_reason,
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }
