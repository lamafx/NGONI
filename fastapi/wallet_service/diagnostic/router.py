"""Endpoints reels du contrat -- copie conforme de DiagnosticController.php.
Ce router ne contient aucune logique metier : voir services/."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.diagnostic.contracts import DiagnosticInvocationRequest

from ..security import require_internal_secret
from .manifest import MANIFEST
from .services.gift import resolve_gift
from .services.topup import resolve_topup
from .services.withdrawal import resolve_withdrawal
from .services.wallet_extras import (
    resolve_coin_purchase, resolve_pending_balance, resolve_video_purchase, resolve_video_sale_revenue, resolve_wallet_frozen,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/diagnostic",
    tags=["diagnostic"],
    dependencies=[Depends(require_internal_secret)],
)


def _log_outcome(endpoint: str, payload: DiagnosticInvocationRequest, result: dict) -> dict:
    detail = result.get("escalation_reason") or result.get("resolution_code")
    logger.info(
        "[DIAG][WALLET_SERVICE] session=%s trace_id=%s stage=endpoint_out endpoint=%s outcome=%s %s",
        payload.session_id, payload.trace_id, endpoint, result.get("outcome"), detail,
    )
    return result


@router.get("/manifest")
def manifest():
    return MANIFEST.model_dump()


@router.post("/withdrawal")
def withdrawal(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    reference = payload.entities.get("transaction_reference")
    incident_date = payload.entities.get("incident_date")
    amount = payload.entities.get("amount")
    # Voie de repli (rapport utilisateur, "champs alternatifs") : reference
    # absente mais date+montant fournis a la place -- voir
    # services/withdrawal.py::_resolve_by_date_amount et manifest.py
    # (fallback_fields de withdrawal_pending).
    if not reference and not (incident_date and amount):
        raise HTTPException(
            status_code=422,
            detail="entities.transaction_reference (ou entities.incident_date + entities.amount) est obligatoire",
        )

    logger.info(
        "[DIAG][WALLET_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=withdrawal user=%s reference=%s fallback=%s",
        payload.session_id, payload.trace_id, payload.user_id, reference, bool(not reference),
    )
    return _log_outcome(
        "withdrawal", payload,
        resolve_withdrawal(db, payload.user_id, reference, incident_date=incident_date, amount=amount),
    )


@router.post("/topup")
def topup(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    reference = payload.entities.get("transaction_reference")
    if not reference:
        raise HTTPException(status_code=422, detail="entities.transaction_reference est obligatoire")

    logger.info(
        "[DIAG][WALLET_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=topup user=%s reference=%s",
        payload.session_id, payload.trace_id, payload.user_id, reference,
    )
    return _log_outcome("topup", payload, resolve_topup(db, payload.user_id, reference))


@router.post("/gift")
def gift(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    reference = payload.entities.get("gift_reference")
    if not reference:
        raise HTTPException(status_code=422, detail="entities.gift_reference est obligatoire")

    logger.info(
        "[DIAG][WALLET_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=gift user=%s reference=%s",
        payload.session_id, payload.trace_id, payload.user_id, reference,
    )
    return _log_outcome("gift", payload, resolve_gift(db, payload.user_id, reference))


@router.post("/wallet_frozen")
def wallet_frozen(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][WALLET_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=wallet_frozen user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("wallet_frozen", payload, resolve_wallet_frozen(db, payload.user_id))


@router.post("/pending_balance")
def pending_balance(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][WALLET_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=pending_balance user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("pending_balance", payload, resolve_pending_balance(db, payload.user_id))


@router.post("/coin_purchase")
def coin_purchase(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][WALLET_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=coin_purchase user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("coin_purchase", payload, resolve_coin_purchase(db, payload.user_id))


@router.post("/video_purchase")
def video_purchase(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][WALLET_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=video_purchase user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("video_purchase", payload, resolve_video_purchase(db, payload.user_id))


@router.post("/video_sale")
def video_sale(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][WALLET_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=video_sale user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("video_sale", payload, resolve_video_sale_revenue(db, payload.user_id))
