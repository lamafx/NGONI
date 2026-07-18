"""Persistance de la tracabilite du Diagnostic Engine (Phase 6, etape 26).
Meme convention que app.domains.complaints.repository : une classe fine
autour d'une Session SQLAlchemy, aucune logique de decision ici (le Pipeline
decide QUOI logger, ce repository decide seulement COMMENT l'ecrire)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import DiagnosticAuditLog, DiagnosticSession

logger = logging.getLogger(__name__)

# outcome.outcome (RESOLVED/ESCALATE/NEED_MORE_INFO) -> statut de session
# affiche. NEED_MORE_INFO reste IN_PROGRESS : la conversation n'est pas
# terminee, d'autres tours suivront avant une vraie resolution/escalade.
_SESSION_STATUS_BY_OUTCOME = {
    "RESOLVED": "RESOLVED",
    "ESCALATE": "ESCALATED",
    "NEED_MORE_INFO": "IN_PROGRESS",
}


class DiagnosticAuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        trace_id: str,
        session_id: str,
        user_id: str | None,
        service: str,
        problem: str,
        called_endpoint: str | None,
        entities: dict,
        outcome: str,
        outcome_detail: str | None,
        latency_ms: int | None,
    ) -> None:
        """Ecrit une ligne d'audit ET met a jour l'etat de la session en une
        seule transaction -- les deux tables doivent toujours rester
        coherentes (jamais un log ecrit sans que la session correspondante
        ne refl ete son dernier etat, ou l'inverse)."""
        self.session.add(
            DiagnosticAuditLog(
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                service=service,
                problem=problem,
                called_endpoint=called_endpoint,
                request_entities=entities,
                outcome=outcome,
                outcome_detail=outcome_detail,
                latency_ms=latency_ms,
            )
        )
        self._upsert_session(
            session_id=session_id,
            user_id=user_id,
            service=service,
            problem=problem,
            outcome=outcome,
            outcome_detail=outcome_detail,
        )
        self.session.commit()

    def _upsert_session(
        self,
        *,
        session_id: str,
        user_id: str | None,
        service: str,
        problem: str,
        outcome: str,
        outcome_detail: str | None,
    ) -> None:
        status = _SESSION_STATUS_BY_OUTCOME.get(outcome, outcome)
        existing = self.session.query(DiagnosticSession).filter_by(session_id=session_id).first()
        if existing is None:
            self.session.add(
                DiagnosticSession(
                    session_id=session_id,
                    user_id=user_id,
                    service=service,
                    problem=problem,
                    status=status,
                    last_outcome=outcome_detail,
                    turns_count=1,
                )
            )
            return
        existing.user_id = user_id or existing.user_id
        existing.service = service
        existing.problem = problem
        existing.status = status
        existing.last_outcome = outcome_detail
        existing.turns_count = (existing.turns_count or 0) + 1
        existing.updated_at = datetime.now(timezone.utc)

    def get_session(self, session_id: str) -> DiagnosticSession | None:
        return self.session.query(DiagnosticSession).filter_by(session_id=session_id).first()

    def link_latest_escalation(self, *, session_id: str, ticket_id: str) -> None:
        """Relie un ticket cree automatiquement (escalade SERVICE_UNAVAILABLE,
        voir router.py::resolve_diagnostic) a la ligne d'audit correspondante.

        Ecriture separee de record() : le ticket n'existe qu'APRES l'appel a
        pipeline.resolve() qui a deja ecrit la ligne d'audit -- pas de
        trace_id transmis jusqu'au routeur pour cibler precisement CETTE
        ligne (aurait exige de changer la signature de
        DiagnosticPipeline.resolve(), qui reste volontairement stable pour ne
        pas affecter les appelants/tests existants). On cible donc la ligne
        ESCALATE/SERVICE_UNAVAILABLE la plus recente non encore liee pour
        cette session -- suffisant en pratique (un seul appel synchrone par
        requete) ; le rare cas concurrent laisserait au pire une ligne non
        liee, jamais une donnee incoherente. Best-effort comme record() :
        une panne ici ne doit jamais faire echouer la reponse deja envoyee a
        l'utilisateur."""
        try:
            row = (
                self.session.query(DiagnosticAuditLog)
                .filter_by(
                    session_id=session_id,
                    outcome="ESCALATE",
                    outcome_detail="SERVICE_UNAVAILABLE",
                    related_ticket_id=None,
                )
                .order_by(DiagnosticAuditLog.created_at.desc())
                .first()
            )
            if row is not None:
                row.related_ticket_id = ticket_id
                self.session.commit()
        except Exception:
            self.session.rollback()
            logger.warning(
                "[DIAG][ENGINE] session=%s stage=audit result=TICKET_LINK_FAILED ticket_id=%s",
                session_id, ticket_id, exc_info=True,
            )
