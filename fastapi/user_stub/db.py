from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class User(Base):
    """Lecture seule sur le schema `users` (clone de la vraie base de
    ngoni-user-service). Seules les colonnes lues par le diagnostic sont
    mappees ici -- ce modele ne doit jamais servir a ecrire."""

    __tablename__ = "users"
    __table_args__ = {"schema": "users"}

    id = Column(UUID(as_uuid=True), primary_key=True)
    status = Column(String, nullable=False)
    kyc_status = Column(String, nullable=False)
    kyc_level = Column(String, nullable=False)
    suspension_reason = Column(String, nullable=True)
    suspended_at = Column(DateTime(timezone=False), nullable=True)
    ban_reason = Column(String, nullable=True)
    banned_at = Column(DateTime(timezone=False), nullable=True)
    compliance_hold = Column(Boolean, nullable=False)
    compliance_hold_until = Column(DateTime(timezone=False), nullable=True)


class KycSubmission(Base):
    """Lecture seule sur `users.kyc_submissions` (clone). Une ligne par
    demande de verification envoyee ; plusieurs lignes possibles par
    utilisateur (nouvelle demande apres un refus)."""

    __tablename__ = "kyc_submissions"
    __table_args__ = {"schema": "users"}

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    level = Column(String, nullable=False)
    status = Column(String, nullable=False)
    rejection_reason = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=False), nullable=True)
    created_at = Column(DateTime(timezone=False), nullable=True)


class ComplianceEvent(Base):
    """Lecture seule sur `users.compliance_events` (clone). Historique des
    declenchements de la moderation automatique (voir ComplianceService cote
    ngoni-user-service) -- une ligne par evenement, pas un etat courant."""

    __tablename__ = "compliance_events"
    __table_args__ = {"schema": "users"}

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    trigger = Column(String, nullable=False)
    action = Column(String, nullable=False)
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=False), nullable=True)


class AccountDeletion(Base):
    """Lecture seule sur `users.account_deletions` (clone). Une ligne par
    demande de suppression (GDPR) ; delai de grace de 30 jours entre
    soft_deleted_at et hard_delete_scheduled_for avant purge definitive."""

    __tablename__ = "account_deletions"
    __table_args__ = {"schema": "users"}

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    deletion_reason = Column(String, nullable=True)
    soft_deleted_at = Column(DateTime(timezone=False), nullable=False)
    hard_delete_scheduled_for = Column(DateTime(timezone=False), nullable=False)
    hard_deleted_at = Column(DateTime(timezone=False), nullable=True)


class ParentalConsent(Base):
    """Lecture seule sur `users.parental_consents` (clone). `child_id` est
    l'utilisateur mineur dont le compte est concerne -- c'est lui qui
    contacte generalement le support, d'ou la recherche par child_id (pas
    parent_id) dans le diagnostic."""

    __tablename__ = "parental_consents"
    __table_args__ = {"schema": "users"}

    id = Column(UUID(as_uuid=True), primary_key=True)
    child_id = Column(UUID(as_uuid=True), nullable=False)
    parent_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String, nullable=False)
    requested_at = Column(DateTime(timezone=False), nullable=False)
    request_expires_at = Column(DateTime(timezone=False), nullable=True)
    verified_at = Column(DateTime(timezone=False), nullable=True)
    rejection_reason = Column(String, nullable=True)
    rejection_reason_code = Column(String, nullable=True)
