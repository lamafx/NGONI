"""Construction des reponses conformes au contrat service-invocation-response
(voir app/domains/diagnostic/contracts.py) : RESOLVED ou ESCALATE.
Partage par tous les domaines de ce service (aujourd'hui : diagnostic/)."""

from app.domains.diagnostic.contracts import EscalateOutcome, EscalationPayload, ResolvedOutcome


def resolved(message: str, code: str, data: dict | None = None) -> dict:
    return ResolvedOutcome(message=message, resolution_code=code, data=data or {}).model_dump()


def escalate(message: str, reason: str, category: str, urgency: str, context: dict) -> dict:
    return EscalateOutcome(
        message=message,
        escalation_reason=reason,
        escalation_payload=EscalationPayload(category=category, urgency=urgency, context=context),
    ).model_dump()
