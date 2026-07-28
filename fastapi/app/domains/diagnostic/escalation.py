"""Relais de l'escalade du Diagnostic Engine vers le systeme de tickets deja
existant (voir docs/diagnostic-roadmap.md, Phase 3). Reutilise ComplaintService
tel quel -- la roadmap notait des le depart que "/tickets/create existe deja
cote FastAPI, reutilisable tel quel pour l'escalade"."""

try:
    from app.domains.complaints.schemas import TicketCreateRequest, TicketCreateResponse
    from app.domains.complaints.service import ComplaintService
except ImportError:  # pragma: no cover - support running as `main`
    from domains.complaints.schemas import TicketCreateRequest, TicketCreateResponse
    from domains.complaints.service import ComplaintService

from .contracts import EscalateOutcome


def escalate_to_ticket(
    service: ComplaintService,
    outcome: EscalateOutcome,
    *,
    user_id: str | None = None,
    created_by: str = "ai_auto_escalation",
) -> TicketCreateResponse:
    payload = TicketCreateRequest(
        category=outcome.escalation_payload.category,
        description=outcome.message,
        urgency=outcome.escalation_payload.urgency,
        summary=f"[Diagnostic] {outcome.escalation_reason}",
        # Escalade decidee par le systeme (pas par une confirmation
        # utilisateur explicite) : c'est precisement ce que ce relais existe
        # pour couvrir, voir router.py et pipeline.py.
        confirmation="oui",
        context={**outcome.escalation_payload.context, "escalation_reason": outcome.escalation_reason},
        user_id=user_id,
        created_by=created_by,
    )
    return service.create_ticket(payload)
