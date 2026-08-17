import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from .models import AgentAction
from .repository import AgentActionRepository
from .schemas import AgentActionCreateRequest, AgentActionResponse

logger = logging.getLogger(__name__)

# Liste blanche fermee (pas un ENUM Postgres, voir models.py) : un nouveau
# domaine d'action doit etre ajoute ici explicitement, pour eviter qu'une
# faute de frappe cote appelant (ex. serveur d'actions Rasa) ne pollue
# silencieusement la table avec des valeurs incoherentes.
#
# "diagnostic_superagent" (2026-07-30) : decisions prises par le mode
# Super-Agent (voir rasa/actions/diagnostic.py, is_superagent_mode) -- une
# action normalement escaladee vers un ticket humain (remboursement d'un
# retrait bloque au-dela du SLA, acceleration d'un dossier KYC en attente)
# est ici executee directement par l'agent. Domaine distinct de
# "diagnostic_classification" : ce ne sont pas des decisions de
# classification mais des decisions D'ACTION, avec un niveau de risque
# different -- separables dans le journal d'activite admin.
ALLOWED_DOMAINS = {"faq", "diagnostic_classification", "diagnostic_superagent"}


class AgentActionService:
    def __init__(self, repository: Optional[AgentActionRepository] = None) -> None:
        self.repository = repository

    def record(self, payload: AgentActionCreateRequest) -> AgentActionResponse:
        if payload.domain not in ALLOWED_DOMAINS:
            raise ValueError(f"Domaine d'action inconnu : {payload.domain!r}")
        if self.repository is None:
            raise RuntimeError("AgentActionService requiert un repository pour persister une action")
        action = self.repository.record(payload)
        return _to_response(action)

    def list_actions(
        self, domain: Optional[str] = None, session_id: Optional[str] = None
    ) -> List[AgentActionResponse]:
        if self.repository is None:
            return []
        return [_to_response(a) for a in self.repository.list_actions(domain=domain, session_id=session_id)]

    @classmethod
    def from_session(cls, session: Session) -> "AgentActionService":
        return cls(AgentActionRepository(session))


def _to_response(action: AgentAction) -> AgentActionResponse:
    return AgentActionResponse(
        id=str(action.id),
        trace_id=action.trace_id,
        session_id=action.session_id,
        user_id=action.user_id,
        domain=action.domain,
        action_type=action.action_type,
        input_data=action.input_data or {},
        output_data=action.output_data or {},
        related_ticket_id=action.related_ticket_id,
        created_at=action.created_at.isoformat() if action.created_at else None,
    )


def record_faq_lookup(
    db: Session,
    *,
    question: str,
    matched_question: Optional[str],
    score: Optional[float],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Aide best-effort partagee entre POST /faq/search (faq/router.py) et le
    raccourci /api/chat (app/main.py) -- les deux appellent
    FaqService.find_best_answer et doivent produire le meme evenement
    d'audit. Ne leve jamais : une panne d'ecriture ne doit pas faire echouer
    la reponse FAQ deja calculee (meme principe que
    app.domains.diagnostic.pipeline._record_audit)."""
    try:
        AgentActionService.from_session(db).record(
            AgentActionCreateRequest(
                session_id=session_id,
                user_id=user_id,
                domain="faq",
                action_type="faq_answer_served" if matched_question else "faq_answer_not_found",
                input_data={"question": question},
                output_data={"matched_question": matched_question, "score": score},
            )
        )
    except Exception:
        logger.warning("Echec de l'enregistrement de l'audit FAQ", exc_info=True)
