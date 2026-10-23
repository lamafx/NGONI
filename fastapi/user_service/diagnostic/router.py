"""Endpoints reels du contrat -- copie conforme des controllers PHP
concernes. Ce router ne contient aucune logique metier : voir services/.

Contrairement a wallet_service, aucun de ces problemes n'exige de champ dans
`entities` : tout se resout a partir de `payload.user_id`, deja fourni par
le Diagnostic Engine (voir manifest.py)."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.diagnostic.contracts import DiagnosticInvocationRequest

from ..security import require_internal_secret
from .manifest import MANIFEST
from .services.account_status import resolve_account_status
from .services.compliance import resolve_compliance_hold
from .services.deletion import resolve_account_deletion
from .services.kyc import resolve_kyc_status
from .services.parental_consent import resolve_parental_consent

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/diagnostic",
    tags=["diagnostic"],
    dependencies=[Depends(require_internal_secret)],
)


def _log_outcome(endpoint: str, payload: DiagnosticInvocationRequest, result: dict) -> dict:
    detail = result.get("escalation_reason") or result.get("resolution_code")
    logger.info(
        "[DIAG][USER_SERVICE] session=%s trace_id=%s stage=endpoint_out endpoint=%s outcome=%s %s",
        payload.session_id, payload.trace_id, endpoint, result.get("outcome"), detail,
    )
    return result


@router.get("/manifest")
def manifest():
    return MANIFEST.model_dump()


@router.post("/kyc_status")
def kyc_status(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][USER_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=kyc_status user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("kyc_status", payload, resolve_kyc_status(db, payload.user_id))


@router.post("/account_status")
def account_status(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][USER_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=account_status user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("account_status", payload, resolve_account_status(db, payload.user_id))


@router.post("/compliance_hold")
def compliance_hold(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][USER_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=compliance_hold user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("compliance_hold", payload, resolve_compliance_hold(db, payload.user_id))


@router.post("/account_deletion")
def account_deletion(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][USER_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=account_deletion user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("account_deletion", payload, resolve_account_deletion(db, payload.user_id))


@router.post("/parental_consent")
def parental_consent(payload: DiagnosticInvocationRequest, db: Session = Depends(get_db)):
    logger.info(
        "[DIAG][USER_SERVICE] session=%s trace_id=%s stage=endpoint_in endpoint=parental_consent user=%s",
        payload.session_id, payload.trace_id, payload.user_id,
    )
    return _log_outcome("parental_consent", payload, resolve_parental_consent(db, payload.user_id))
