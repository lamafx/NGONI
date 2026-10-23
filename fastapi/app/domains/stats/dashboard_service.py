"""Agregats du tableau de bord d'administration.

Tout est compte en SQL sur des tables reellement alimentees -- aucune valeur
d'illustration. Les deux nouveautes par rapport a /admin/stats/overview :

  - les DELTAS periode sur periode (la meme mesure sur la fenetre
    precedente de duree identique), demandes par les cartes KPI ;
  - la repartition des INTENTIONS, qui n'etait pas calculable jusqu'ici
    faute de telemetrie : POST /api/chat classifiait sans rien ecrire. Elle
    lit maintenant ia.conversation_messages.intent, renseigne a chaque tour
    par le meme classifieur qui pilote la reponse -- donc la distribution
    reelle du moteur, pas une re-classification a posteriori.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

try:
    from app.domains.audit.models import AgentAction
    from app.domains.complaints.models import Complaint
    from app.domains.conversations.models import (
        STATUS_ASSIGNED,
        STATUS_ESCALATED,
        STATUS_RESOLVED,
        Conversation,
        ConversationMessage,
    )
    from app.domains.diagnostic.models import DiagnosticAuditLog, DiagnosticSession
except ImportError:  # pragma: no cover - support running as `main`
    from domains.audit.models import AgentAction
    from domains.complaints.models import Complaint
    from domains.conversations.models import (
        STATUS_ASSIGNED,
        STATUS_ESCALATED,
        STATUS_RESOLVED,
        Conversation,
        ConversationMessage,
    )
    from domains.diagnostic.models import DiagnosticAuditLog, DiagnosticSession

from .dashboard_schemas import (  # noqa: I001
    ActivityItem,
    ConversationVolumeResponse,
    DashboardSummaryResponse,
    DiagnosticAuditEntry,
    DiagnosticProblemsResponse,
    DiagnosticProblemStats,
    DiagnosticRunsPoint,
    DiagnosticRunsResponse,
    DiagnosticSessionDetail,
    DiagnosticSessionItem,
    DiagnosticSessionsResponse,
    IntentDistributionResponse,
    IntentSlice,
    KpiValue,
    RecentActivityResponse,
    VolumePoint,
)

logger = logging.getLogger(__name__)

DEFAULT_PERIOD_DAYS = 7

_WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

# Une conversation est "en cours" si elle n'est pas resolue ET a bouge
# recemment. Sans cette seconde condition, une conversation abandonnee il y a
# trois semaines resterait comptee comme active indefiniment.
ACTIVE_WINDOW_HOURS = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _delta_pct(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous in (None, 0):
        return None
    return round(((current - previous) / previous) * 100, 1)


def _kpi(current: Optional[float], previous: Optional[float]) -> KpiValue:
    return KpiValue(value=current, previous=previous, delta_pct=_delta_pct(current, previous))


class DashboardService:
    def __init__(self, session: Session) -> None:
        self.session = session

    @classmethod
    def from_session(cls, session: Session) -> "DashboardService":
        return cls(session)

    # ---- KPI -------------------------------------------------------------

    def summary(self, days: int = DEFAULT_PERIOD_DAYS) -> DashboardSummaryResponse:
        now = _now()
        current_start = now - timedelta(days=days)
        previous_start = now - timedelta(days=days * 2)

        tickets_treated = self._tickets_treated(current_start, now)
        tickets_treated_prev = self._tickets_treated(previous_start, current_start)
        users_helped = self._users_helped(current_start, now)
        users_helped_prev = self._users_helped(previous_start, current_start)
        response_ms = self._avg_response_time_ms(current_start, now)
        response_ms_prev = self._avg_response_time_ms(previous_start, current_start)

        active_since = now - timedelta(hours=ACTIVE_WINDOW_HOURS)
        in_progress = (
            self.session.query(func.count())
            .select_from(Conversation)
            .filter(
                Conversation.status != STATUS_RESOLVED,
                Conversation.last_message_at >= active_since,
            )
            .scalar()
            or 0
        )
        in_progress_prev = (
            self.session.query(func.count())
            .select_from(Conversation)
            .filter(
                Conversation.status != STATUS_RESOLVED,
                Conversation.last_message_at >= active_since - timedelta(hours=ACTIVE_WINDOW_HOURS),
                Conversation.last_message_at < active_since,
            )
            .scalar()
            or 0
        )

        conversations_period = (
            self.session.query(func.count())
            .select_from(Conversation)
            .filter(Conversation.created_at >= current_start)
            .scalar()
            or 0
        )
        escalated_period = (
            self.session.query(func.count())
            .select_from(Conversation)
            .filter(Conversation.created_at >= current_start, Conversation.escalated.is_(True))
            .scalar()
            or 0
        )

        return DashboardSummaryResponse(
            generated_at=now.isoformat(),
            period_days=days,
            conversations_in_progress=_kpi(float(in_progress), float(in_progress_prev)),
            tickets_treated=_kpi(float(tickets_treated), float(tickets_treated_prev)),
            users_helped=_kpi(float(users_helped), float(users_helped_prev)),
            avg_response_time_ms=_kpi(response_ms, response_ms_prev),
            escalation_rate=(
                round(escalated_period / conversations_period * 100, 1)
                if conversations_period
                else None
            ),
            handled_by_agents=(
                self.session.query(func.count())
                .select_from(Conversation)
                .filter(Conversation.status == STATUS_ASSIGNED)
                .scalar()
                or 0
            ),
            conversations_waiting=(
                self.session.query(func.count())
                .select_from(Conversation)
                .filter(Conversation.status == STATUS_ESCALATED)
                .scalar()
                or 0
            ),
            conversations_total=(
                self.session.query(func.count()).select_from(Conversation).scalar() or 0
            ),
            tickets_open=(
                self.session.query(func.count())
                .select_from(Complaint)
                .filter(Complaint.status.notin_(["RESOLVED", "CLOSED"]))
                .scalar()
                or 0
            ),
            agents_online=self._agents_online(now),
            users_total=int(
                self.session.query(
                    func.count(
                        func.distinct(
                            func.coalesce(Conversation.user_id, Conversation.conversation_id)
                        )
                    )
                ).scalar()
                or 0
            ),
        )

    def _agents_online(self, now: datetime) -> int:
        """Meme regle que AgentService.effective_status, appliquee en SQL :
        un conseiller declare en ligne mais sans activite depuis
        PRESENCE_TIMEOUT_MINUTES ne compte pas. Dupliquer la regle en deux
        endroits serait le meilleur moyen de les faire diverger -- d'ou
        l'import de la constante, jamais une valeur reecrite ici."""
        try:
            try:
                from app.domains.agents.models import STATUS_OFFLINE, SupportAgent
                from app.domains.agents.service import PRESENCE_TIMEOUT_MINUTES
            except ImportError:  # pragma: no cover - support running as `main`
                from domains.agents.models import STATUS_OFFLINE, SupportAgent
                from domains.agents.service import PRESENCE_TIMEOUT_MINUTES

            threshold = now - timedelta(minutes=PRESENCE_TIMEOUT_MINUTES)
            return int(
                self.session.query(func.count())
                .select_from(SupportAgent)
                .filter(
                    SupportAgent.status != STATUS_OFFLINE,
                    SupportAgent.last_seen_at.isnot(None),
                    SupportAgent.last_seen_at >= threshold,
                )
                .scalar()
                or 0
            )
        except Exception as error:  # pragma: no cover - lecture best-effort
            logger.warning("Compteur de conseillers en ligne indisponible (%s)", error)
            return 0

    def _tickets_treated(self, start: datetime, end: datetime) -> int:
        return int(
            self.session.query(func.count())
            .select_from(Complaint)
            .filter(
                Complaint.status.in_(["RESOLVED", "CLOSED"]),
                Complaint.updated_at >= start,
                Complaint.updated_at < end,
            )
            .scalar()
            or 0
        )

    def _users_helped(self, start: datetime, end: datetime) -> int:
        """Usagers DISTINCTS ayant echange avec le support sur la periode.
        Compte les conversations distinctes quand aucune identite n'est
        connue (page /chat sans utilisateur authentifie) : une conversation
        anonyme reste une personne aidee."""
        return int(
            self.session.query(
                func.count(func.distinct(func.coalesce(Conversation.user_id, Conversation.conversation_id)))
            )
            .filter(Conversation.last_message_at >= start, Conversation.last_message_at < end)
            .scalar()
            or 0
        )

    def _avg_response_time_ms(self, start: datetime, end: datetime) -> Optional[float]:
        """Delai moyen entre un message d'usager et la reponse qui suit dans
        la MEME conversation. Calcule en une seule requete fenetree cote
        Postgres : le faire en Python demanderait de rapatrier tous les
        messages de la periode."""
        query = text(
            """
            WITH ordered AS (
                SELECT
                    conversation_id,
                    sender_role,
                    created_at,
                    LEAD(created_at) OVER (
                        PARTITION BY conversation_id ORDER BY created_at
                    ) AS next_at,
                    LEAD(sender_role) OVER (
                        PARTITION BY conversation_id ORDER BY created_at
                    ) AS next_role
                FROM ia.conversation_messages
                WHERE created_at >= :start AND created_at < :end
            )
            SELECT AVG(EXTRACT(EPOCH FROM (next_at - created_at)) * 1000)
            FROM ordered
            WHERE sender_role = 'user' AND next_role IN ('bot', 'agent')
            """
        )
        try:
            value = self.session.execute(query, {"start": start, "end": end}).scalar()
        except Exception as error:  # pragma: no cover - lecture best-effort
            logger.warning("Temps de reponse moyen indisponible (%s)", error)
            return None
        return round(float(value), 1) if value is not None else None

    # ---- series ----------------------------------------------------------

    def conversation_volume(self, days: int = DEFAULT_PERIOD_DAYS) -> ConversationVolumeResponse:
        start = _now() - timedelta(days=days)
        rows = (
            self.session.query(
                func.date(ConversationMessage.created_at).label("day"),
                func.count(func.distinct(ConversationMessage.conversation_id)),
                func.count(),
            )
            .filter(ConversationMessage.created_at >= start)
            .group_by("day")
            .all()
        )
        by_day: Dict[date, Tuple[int, int]] = {
            _as_date(day): (int(conversations), int(messages)) for day, conversations, messages in rows
        }
        points: List[VolumePoint] = []
        today = _now().date()
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            conversations, messages = by_day.get(day, (0, 0))
            points.append(
                VolumePoint(
                    date=day.isoformat(),
                    label=_WEEKDAYS[day.weekday()],
                    conversations=conversations,
                    messages=messages,
                )
            )
        return ConversationVolumeResponse(
            period_days=days, points=points, total=sum(point.conversations for point in points)
        )

    def intent_distribution(self, days: int = DEFAULT_PERIOD_DAYS) -> IntentDistributionResponse:
        start = _now() - timedelta(days=days)
        rows = (
            self.session.query(
                ConversationMessage.intent,
                func.count(),
                func.avg(ConversationMessage.confidence),
            )
            .filter(
                ConversationMessage.created_at >= start,
                ConversationMessage.sender_role == "user",
                ConversationMessage.intent.isnot(None),
            )
            .group_by(ConversationMessage.intent)
            .order_by(func.count().desc())
            .all()
        )
        unclassified = int(
            self.session.query(func.count())
            .select_from(ConversationMessage)
            .filter(
                ConversationMessage.created_at >= start,
                ConversationMessage.sender_role == "user",
                ConversationMessage.intent.is_(None),
            )
            .scalar()
            or 0
        )
        total = sum(int(count) for _, count, _ in rows)
        categories = [
            IntentSlice(
                intent=intent,
                count=int(count),
                value_pct=round(int(count) / total * 100, 1) if total else 0.0,
                avg_confidence=round(float(confidence), 3) if confidence is not None else None,
            )
            for intent, count, confidence in rows
        ]
        return IntentDistributionResponse(
            period_days=days,
            total_messages=total,
            distinct_intents=len(categories),
            categories=categories,
            unclassified=unclassified,
        )

    def recent_activity(self, limit: int = 10) -> RecentActivityResponse:
        """Flux d'evenements recents, reconstitue depuis les traces
        existantes. Chaque entree correspond a une ligne reellement ecrite en
        base (ticket, escalade, prise en charge, action autonome)."""
        items: List[ActivityItem] = []

        for complaint in (
            self.session.query(Complaint).order_by(Complaint.created_at.desc()).limit(limit).all()
        ):
            items.append(
                ActivityItem(
                    at=_iso(complaint.created_at),
                    kind="ticket",
                    label=f"Ticket {complaint.ticket_id} créé ({complaint.category})",
                    detail=complaint.summary,
                )
            )

        for conversation in (
            self.session.query(Conversation)
            .filter(Conversation.escalated_at.isnot(None))
            .order_by(Conversation.escalated_at.desc())
            .limit(limit)
            .all()
        ):
            items.append(
                ActivityItem(
                    at=_iso(conversation.escalated_at),
                    kind="escalade",
                    label=f"Conversation {conversation.conversation_id} escaladée",
                    detail=conversation.escalation_reason,
                )
            )
            if conversation.assigned_at:
                items.append(
                    ActivityItem(
                        at=_iso(conversation.assigned_at),
                        kind="prise_en_charge",
                        label=f"Conversation {conversation.conversation_id} prise en charge",
                        detail=conversation.assigned_to,
                    )
                )

        for action in (
            self.session.query(AgentAction).order_by(AgentAction.created_at.desc()).limit(limit).all()
        ):
            items.append(
                ActivityItem(
                    at=_iso(action.created_at),
                    kind=action.domain,
                    label=f"{action.action_type}",
                    detail=action.session_id,
                )
            )

        items.sort(key=lambda item: item.at or "", reverse=True)
        return RecentActivityResponse(items=items[:limit])

    def diagnostic_runs(self, days: int = DEFAULT_PERIOD_DAYS) -> DiagnosticRunsResponse:
        """Lecture seule sur ia.diagnostic_audit_log, deja alimentee a chaque
        appel de /diagnostic/resolve -- aucune instrumentation nouvelle."""
        start = _now() - timedelta(days=days)
        total = int(
            self.session.query(func.count())
            .select_from(DiagnosticAuditLog)
            .filter(DiagnosticAuditLog.created_at >= start)
            .scalar()
            or 0
        )
        avg_latency = (
            self.session.query(func.avg(DiagnosticAuditLog.latency_ms))
            .filter(DiagnosticAuditLog.created_at >= start)
            .scalar()
        )
        by_outcome = [
            {"label": outcome, "value": int(count)}
            for outcome, count in (
                self.session.query(DiagnosticAuditLog.outcome, func.count())
                .filter(DiagnosticAuditLog.created_at >= start)
                .group_by(DiagnosticAuditLog.outcome)
                .all()
            )
        ]
        rows = (
            self.session.query(
                func.date(DiagnosticAuditLog.created_at).label("day"),
                func.count(),
                func.avg(DiagnosticAuditLog.latency_ms),
            )
            .filter(DiagnosticAuditLog.created_at >= start)
            .group_by("day")
            .all()
        )
        by_day = {
            _as_date(day): (int(count), int(latency) if latency is not None else None)
            for day, count, latency in rows
        }
        today = _now().date()
        points = []
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            runs, latency = by_day.get(day, (0, None))
            points.append(DiagnosticRunsPoint(date=day.isoformat(), runs=runs, avg_latency_ms=latency))
        return DiagnosticRunsResponse(
            period_days=days,
            runs_total=total,
            avg_latency_ms=int(avg_latency) if avg_latency is not None else None,
            by_outcome=by_outcome,
            points=points,
        )

    def diagnostic_problems(self, days: int = DEFAULT_PERIOD_DAYS) -> DiagnosticProblemsResponse:
        """Bilan par probleme diagnosticable (service, problem) : volume,
        issues, et causes les plus frequentes (outcome_detail). C'est ce qui
        montre OU le diagnostic echoue -- un taux d'escalade global ne dit
        pas quel probleme le tire vers le haut."""
        start = _now() - timedelta(days=days)
        rows = (
            self.session.query(
                DiagnosticAuditLog.service,
                DiagnosticAuditLog.problem,
                DiagnosticAuditLog.outcome,
                DiagnosticAuditLog.outcome_detail,
                func.count(),
                func.avg(DiagnosticAuditLog.latency_ms),
                func.max(DiagnosticAuditLog.created_at),
            )
            .filter(DiagnosticAuditLog.created_at >= start)
            .group_by(
                DiagnosticAuditLog.service,
                DiagnosticAuditLog.problem,
                DiagnosticAuditLog.outcome,
                DiagnosticAuditLog.outcome_detail,
            )
            .all()
        )
        buckets: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for service, problem, outcome, detail, count, latency, last_at in rows:
            bucket = buckets.setdefault(
                (service, problem),
                {"counts": {}, "details": {}, "latency_sum": 0.0, "latency_n": 0, "last_at": None},
            )
            count = int(count)
            bucket["counts"][outcome] = bucket["counts"].get(outcome, 0) + count
            if detail:
                key = (outcome, detail)
                bucket["details"][key] = bucket["details"].get(key, 0) + count
            if latency is not None:
                bucket["latency_sum"] += float(latency) * count
                bucket["latency_n"] += count
            if last_at is not None and (bucket["last_at"] is None or last_at > bucket["last_at"]):
                bucket["last_at"] = last_at

        problems = []
        for (service, problem), bucket in buckets.items():
            counts = bucket["counts"]
            resolved = counts.get("RESOLVED", 0)
            escalated = counts.get("ESCALATE", 0)
            concluded = resolved + escalated
            top = sorted(bucket["details"].items(), key=lambda item: -item[1])[:5]
            problems.append(
                DiagnosticProblemStats(
                    service=service,
                    problem=problem,
                    runs=sum(counts.values()),
                    resolved=resolved,
                    escalated=escalated,
                    need_more_info=counts.get("NEED_MORE_INFO", 0),
                    resolution_rate=round(resolved / concluded, 4) if concluded else None,
                    avg_latency_ms=(
                        int(bucket["latency_sum"] / bucket["latency_n"]) if bucket["latency_n"] else None
                    ),
                    top_details=[
                        {"outcome": outcome, "detail": detail, "count": count}
                        for (outcome, detail), count in top
                    ],
                    last_run_at=_iso(bucket["last_at"]),
                )
            )
        problems.sort(key=lambda p: -p.runs)
        return DiagnosticProblemsResponse(period_days=days, problems=problems)

    def diagnostic_sessions(
        self,
        days: int = DEFAULT_PERIOD_DAYS,
        status: Optional[str] = None,
        service: Optional[str] = None,
        problem: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DiagnosticSessionsResponse:
        query = self.session.query(DiagnosticSession).filter(
            DiagnosticSession.updated_at >= _now() - timedelta(days=days)
        )
        if status:
            query = query.filter(DiagnosticSession.status == status)
        if service:
            query = query.filter(DiagnosticSession.service == service)
        if problem:
            query = query.filter(DiagnosticSession.problem == problem)
        total = query.count()
        sessions = (
            query.order_by(DiagnosticSession.updated_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        # Dernier appel de chaque session, en UNE requete (pas une par ligne).
        latest: Dict[str, DiagnosticAuditLog] = {}
        if sessions:
            for log in (
                self.session.query(DiagnosticAuditLog)
                .filter(DiagnosticAuditLog.session_id.in_([s.session_id for s in sessions]))
                .order_by(DiagnosticAuditLog.created_at.asc())
                .all()
            ):
                latest[log.session_id] = log
        return DiagnosticSessionsResponse(
            total=total,
            items=[_session_item(s, latest.get(s.session_id)) for s in sessions],
        )

    def diagnostic_session_detail(self, session_id: str) -> Optional[DiagnosticSessionDetail]:
        session_row = self.session.query(DiagnosticSession).filter_by(session_id=session_id).first()
        if session_row is None:
            return None
        calls = (
            self.session.query(DiagnosticAuditLog)
            .filter(DiagnosticAuditLog.session_id == session_id)
            .order_by(DiagnosticAuditLog.created_at.asc())
            .all()
        )
        item = _session_item(session_row, calls[-1] if calls else None)
        return DiagnosticSessionDetail(
            **item.model_dump(),
            calls=[
                DiagnosticAuditEntry(
                    trace_id=call.trace_id,
                    service=call.service,
                    problem=call.problem,
                    called_endpoint=call.called_endpoint,
                    request_entities=call.request_entities,
                    outcome=call.outcome,
                    outcome_detail=call.outcome_detail,
                    latency_ms=call.latency_ms,
                    related_ticket_id=call.related_ticket_id,
                    created_at=_iso(call.created_at),
                )
                for call in calls
            ],
        )


def _session_item(session_row: Any, last_call: Optional[Any]) -> DiagnosticSessionItem:
    return DiagnosticSessionItem(
        session_id=session_row.session_id,
        user_id=session_row.user_id,
        service=session_row.service,
        problem=session_row.problem,
        status=session_row.status,
        last_outcome=session_row.last_outcome,
        last_outcome_detail=last_call.outcome_detail if last_call else None,
        related_ticket_id=last_call.related_ticket_id if last_call else None,
        turns_count=session_row.turns_count or 0,
        created_at=_iso(session_row.created_at),
        updated_at=_iso(session_row.updated_at),
    )


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
