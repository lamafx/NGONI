from sqlalchemy import Boolean, Column, DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class Wallet(Base):
    """Lecture seule sur le schema `wallet` (clone de la vraie base de
    ngoni-wallet-service). Seules les colonnes lues par le diagnostic sont
    mappees ici -- ce modele ne doit jamais servir a ecrire."""

    __tablename__ = "wallets"
    __table_args__ = {"schema": "wallet"}

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    kyc_verified = Column(Boolean, nullable=False)
    status = Column(String, nullable=False)
    frozen_reason = Column(String, nullable=True)
    frozen_at = Column(DateTime(timezone=True), nullable=True)
    currency = Column(String, nullable=True)
    monthly_limit = Column(Numeric, nullable=True)
    total_withdrawals = Column(Numeric, nullable=True)


class WalletTransaction(Base):
    """Lecture seule sur le schema `wallet` (clone). Idem : sous-ensemble de
    colonnes utile au diagnostic de retrait uniquement."""

    __tablename__ = "wallet_transactions"
    __table_args__ = {"schema": "wallet"}

    id = Column(UUID(as_uuid=True), primary_key=True)
    wallet_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    reference_id = Column(String, nullable=False)
    provider_transaction_id = Column(String, nullable=True)
    error_code = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    amount = Column(Numeric, nullable=True)
    currency = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
