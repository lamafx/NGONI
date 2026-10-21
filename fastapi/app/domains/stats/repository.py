"""Lectures agregees, en SQL, des tables deja alimentees par les autres
domaines (tickets, journal d'audit, sessions de diagnostic, feedback, FAQ).

Ce domaine ne possede AUCUNE table : il ne fait que compter ce que les autres
ecrivent. D'ou l'absence de models.py -- les modeles sont importes depuis
leur domaine d'origine, jamais redeclares ici (une seconde declaration de la
meme table donnerait deux sources de verite sur le meme schema).

Tout est agrege cote Postgres (GROUP BY), jamais en Python apres un SELECT
complet : la page d'administration doit rester juste avec des dizaines de
milliers de lignes, et ne doit pas dependre du `limit` de
/admin/complaints/ (50 par defaut) pour obtenir un total exact -- c'est
precisement ce qui rendait les compteurs de la page faux.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional, Tuple

from sqlalchemy import Date, Numeric, and_, cast, func
from sqlalchemy.orm import Session

try:
    from app.domains.audit.models import AgentAction
    from app.domains.complaints.models import Complaint
    from app.domains.diagnostic.models import DiagnosticAuditLog, DiagnosticSession
    from app.domains.faq.models import FaqItem
    from app.domains.feedback.models import FeedbackEntry, ResponseRating
except ImportError:  # pragma: no cover - support running as `main`
    from domains.audit.models import AgentAction
    from domains.complaints.models import Complaint
    from domains.diagnostic.models import DiagnosticAuditLog, DiagnosticSession
    from domains.faq.models import FaqItem
    from domains.feedback.models import FeedbackEntry, ResponseRating

Slice = Tuple[str, int]

# Score de similarite serialise en texte dans output_data (JSONB) : le cast
# numerique echouerait sur toute la requete si une seule ligne contenait
# autre chose qu'un nombre (ancien format, null explicite).
_NUMERIC_TEXT = r"^[0-9]+(\.[0-9]+)?$"


class StatsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---- utilitaires -----------------------------------------------------

    def _count(self, model, *filters) -> int:
        query = self.session.query(func.count()).select_from(model)
        for condition in filters:
            query = query.filter(condition)
        return int(query.scalar() or 0)

    def _group(self, model, column, *, limit: Optional[int] = None, where=None) -> List[Slice]:
        query = self.session.query(column, func.count().label("n")).select_from(model)
        if where is not None:
            query = query.filter(where)
        query = query.group_by(column).order_by(func.count().desc())
        if limit is not None:
            query = query.limit(limit)
        # `label or "—"` : les colonnes de regroupement sont nullables cote
        # base (urgence d'un ticket importe, service d'une session abandonnee
        # avant classification) -- un None traverserait le schema Pydantic en
        # erreur de validation plutot qu'en ligne "non renseigne".
        return [(str(label) if label is not None else "—", int(count)) for label, count in query.all()]

    def _daily(self, model, since: date, *, where=None) -> List[Tuple[date, int]]:
        day = cast(model.created_at, Date)
        query = self.session.query(day.label("d"), func.count().label("n")).select_from(model).filter(day >= since)
        if where is not None:
            query = query.filter(where)
        rows = query.group_by(day).order_by(day).all()
        return [(d, int(n)) for d, n in rows]

    # ---- volumes ---------------------------------------------------------

    def activity_bounds(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """(premiere trace, derniere trace) toutes sources confondues --
        bornes des series temporelles (voir schemas.StatsPeriod)."""
        firsts = [
            self.session.query(func.min(Complaint.created_at)).scalar(),
            self.session.query(func.min(DiagnosticSession.created_at)).scalar(),
            self.session.query(func.min(AgentAction.created_at)).scalar(),
        ]
        lasts = [
            self.session.query(func.max(Complaint.created_at)).scalar(),
            self.session.query(func.max(DiagnosticSession.created_at)).scalar(),
            self.session.query(func.max(AgentAction.created_at)).scalar(),
        ]
        known_firsts = [stamp for stamp in firsts if stamp is not None]
        known_lasts = [stamp for stamp in lasts if stamp is not None]
        if not known_firsts or not known_lasts:
            return None, None
        return min(known_firsts), max(known_lasts)

    def tickets_total(self) -> int:
        return self._count(Complaint)

    def tickets_closed(self) -> int:
        """RESOLVED + CLOSED -- les deux etats terminaux de la contrainte
        chk_complaints_status (voir init_db.sql)."""
        return self._count(Complaint, Complaint.status.in_(("RESOLVED", "CLOSED")))

    def conversations_total(self) -> int:
        return self._count(DiagnosticSession)

    def conversations_resolved(self) -> int:
        return self._count(DiagnosticSession, DiagnosticSession.status == "RESOLVED")

    def escalations_total(self) -> int:
        return self._count(DiagnosticAuditLog, DiagnosticAuditLog.outcome == "ESCALATE")

    def agent_actions_total(self) -> int:
        return self._count(AgentAction)

    def feedback_entries_total(self) -> int:
        return self._count(FeedbackEntry)

    def avg_latency_ms(self) -> Optional[int]:
        """Latence moyenne des appels du Diagnostic Engine aux microservices
        (ia.diagnostic_audit_log.latency_ms) -- PAS le temps de reponse
        percu par l'utilisateur, qui n'est journalise nulle part."""
        value = (
            self.session.query(func.avg(DiagnosticAuditLog.latency_ms))
            .filter(DiagnosticAuditLog.latency_ms.isnot(None))
            .scalar()
        )
        return int(round(float(value))) if value is not None else None

    # ---- taux ------------------------------------------------------------

    def ratings(self) -> Tuple[int, int]:
        """(total, juges utiles) sur ia.response_ratings."""
        total = self._count(ResponseRating)
        useful = self._count(ResponseRating, ResponseRating.is_useful.is_(True))
        return total, useful

    def faq_lookup_counts(self) -> Tuple[int, int]:
        """(reponses servies, questions restees sans reponse) -- les deux
        action_type ecrits par audit.service.record_faq_lookup."""
        served = self._count(AgentAction, AgentAction.action_type == "faq_answer_served")
        missed = self._count(AgentAction, AgentAction.action_type == "faq_answer_not_found")
        return served, missed

    def avg_faq_score(self) -> Optional[float]:
        """Similarite moyenne des reponses FAQ effectivement servies."""
        expr = AgentAction.output_data["score"].astext
        value = (
            self.session.query(func.avg(cast(expr, Numeric)))
            .select_from(AgentAction)
            .filter(AgentAction.action_type == "faq_answer_served")
            .filter(expr.op("~")(_NUMERIC_TEXT))
            .scalar()
        )
        return round(float(value), 3) if value is not None else None

    # ---- repartitions ----------------------------------------------------

    def tickets_by_category(self) -> List[Slice]:
        return self._group(Complaint, Complaint.category)

    def tickets_by_urgency(self) -> List[Slice]:
        return self._group(Complaint, Complaint.urgency)

    def tickets_by_status(self) -> List[Slice]:
        return self._group(Complaint, Complaint.status)

    def tickets_by_origin(self) -> List[Slice]:
        return self._group(Complaint, Complaint.created_by)

    def actions_by_domain(self) -> List[Slice]:
        return self._group(AgentAction, AgentAction.domain)

    def actions_by_type(self) -> List[Slice]:
        return self._group(AgentAction, AgentAction.action_type)

    def diagnostic_by_service(self) -> List[Slice]:
        return self._group(DiagnosticAuditLog, DiagnosticAuditLog.service)

    def top_problems(self, limit: int = 8) -> List[Slice]:
        return self._group(DiagnosticAuditLog, DiagnosticAuditLog.problem, limit=limit)

    def top_faq_questions(self, limit: int = 8) -> List[Slice]:
        expr = AgentAction.output_data["matched_question"].astext
        return self._group(
            AgentAction,
            expr,
            limit=limit,
            where=and_(AgentAction.action_type == "faq_answer_served", expr.isnot(None)),
        )

    def unanswered_questions(self, limit: int = 8) -> List[Slice]:
        """Questions posees pour lesquelles aucune entree FAQ n'a depasse le
        seuil de similarite -- la liste la plus actionnable de la page :
        chaque ligne est une entree de base de connaissances a ecrire."""
        expr = AgentAction.input_data["question"].astext
        return self._group(
            AgentAction,
            expr,
            limit=limit,
            where=and_(AgentAction.action_type == "faq_answer_not_found", expr.isnot(None)),
        )

    # ---- inventaire ------------------------------------------------------

    def faq_counts(self) -> Tuple[int, int]:
        total = self._count(FaqItem)
        published = self._count(FaqItem, FaqItem.status == "PUBLISHED")
        return total, published

    # ---- series temporelles ----------------------------------------------

    def daily_conversations(self, since: date) -> List[Tuple[date, int]]:
        return self._daily(DiagnosticSession, since)

    def daily_tickets(self, since: date) -> List[Tuple[date, int]]:
        return self._daily(Complaint, since)

    def daily_faq_lookups(self, since: date) -> List[Tuple[date, int]]:
        return self._daily(AgentAction, since, where=AgentAction.domain == "faq")
