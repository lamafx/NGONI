"""API « support » de wallet_service, en lecture seule : le portefeuille d'un
usager tel qu'un conseiller humain doit le voir avant de lui repondre
(solde, statut, dernieres operations). Appelee par le moteur
(app/domains/support), jamais par le Diagnostic Engine.

  GET /api/v1/support/wallets/{user_id}
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

from .security import require_internal_secret

router = APIRouter(
    prefix="/api/v1/support",
    tags=["support"],
    dependencies=[Depends(require_internal_secret)],
)

TRANSACTIONS_SHOWN = 10


def _num(value):
    return float(value) if value is not None else None


@router.get("/wallets/{user_id}")
def get_wallet(user_id: str, db: Session = Depends(get_db)):
    try:
        uid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Portefeuille introuvable") from exc

    wallet = db.execute(
        text(
            "SELECT id, balance, pending_balance, currency, status, frozen_reason, kyc_verified, "
            "total_earned, total_withdrawals, last_withdrawal_at, created_at "
            "FROM wallet.wallets WHERE user_id = :uid"
        ),
        {"uid": uid},
    ).mappings().first()
    if wallet is None:
        raise HTTPException(status_code=404, detail="Portefeuille introuvable")

    transactions = db.execute(
        text(
            "SELECT reference_id, type, status, amount, currency, provider, error_code, created_at "
            "FROM wallet.wallet_transactions WHERE wallet_id = :wid "
            "ORDER BY created_at DESC NULLS LAST LIMIT :n"
        ),
        {"wid": wallet["id"], "n": TRANSACTIONS_SHOWN},
    ).mappings()

    return {
        "user_id": str(uid),
        "balance": _num(wallet["balance"]),
        "pending_balance": _num(wallet["pending_balance"]),
        "currency": wallet["currency"],
        "status": wallet["status"],
        "frozen_reason": wallet["frozen_reason"],
        "kyc_verified": wallet["kyc_verified"],
        "total_earned": _num(wallet["total_earned"]),
        "total_withdrawals": _num(wallet["total_withdrawals"]),
        "last_withdrawal_at": wallet["last_withdrawal_at"].isoformat() if wallet["last_withdrawal_at"] else None,
        "created_at": wallet["created_at"].isoformat() if wallet["created_at"] else None,
        "transactions": [
            {
                "reference": row["reference_id"],
                "type": row["type"],
                "status": row["status"],
                "amount": _num(row["amount"]),
                "currency": row["currency"],
                "provider": row["provider"],
                "error_code": row["error_code"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in transactions
        ],
    }
