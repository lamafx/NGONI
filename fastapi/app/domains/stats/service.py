"""Assemblage de la vue d'ensemble servie a la page d'administration
"Statistiques" (frontend/src/pages/AdminStatsPage.jsx).

Avant ce domaine, la page recalculait tout cote navigateur a partir de
/admin/complaints/ (plafonne a 50 lignes) et /audit/actions : les totaux
etaient donc faux des que la base depassait quelques dizaines de tickets, et
tombaient a zero des que le moteur ne repondait pas. Tout est desormais
compte en base, en une seule requete HTTP.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from .repository import StatsRepository
from .schemas import (
    StatSlice,
    StatsInventory,
    StatsKpis,
    StatsOverviewResponse,
    StatsPeriod,
    StatsTimePoint,
)

DEFAULT_PERIOD_DAYS = 90


class StatsService:
    def __init__(self, repository: Optional[StatsRepository] = None) -> None:
        self.repository = repository

    @classmethod
    def from_session(cls, session: Session) -> "StatsService":
        return cls(StatsRepository(session))

    def overview(self, days: int = DEFAULT_PERIOD_DAYS) -> StatsOverviewResponse:
        if self.repository is None:
            raise RuntimeError("StatsService requiert un repository pour lire les compteurs")
        repo = self.repository

        tickets_total = repo.tickets_total()
        tickets_closed = repo.tickets_closed()
        conversations = repo.conversations_total()
        conversations_resolved = repo.conversations_resolved()
        ratings_total, ratings_useful = repo.ratings()
        faq_served, faq_missed = repo.faq_lookup_counts()
        faq_total, faq_published = repo.faq_counts()

        kpis = StatsKpis(
            conversations=conversations,
            tickets_total=tickets_total,
            tickets_open=tickets_total - tickets_closed,
            tickets_resolved=tickets_closed,
            escalations=repo.escalations_total(),
            agent_actions=repo.agent_actions_total(),
            feedback_entries=repo.feedback_entries_total(),
            ratings_total=ratings_total,
            auto_resolution_rate=_rate(conversations_resolved, conversations),
            faq_answer_rate=_rate(faq_served, faq_served + faq_missed),
            satisfaction_rate=_rate(ratings_useful, ratings_total),
            avg_faq_score=repo.avg_faq_score(),
            avg_latency_ms=repo.avg_latency_ms(),
        )

        period, timeseries = self._timeseries(days)

        return StatsOverviewResponse(
            generated_at=datetime.now(timezone.utc).isoformat(),
            period=period,
            kpis=kpis,
            tickets_by_category=_slices(repo.tickets_by_category()),
            tickets_by_urgency=_slices(repo.tickets_by_urgency()),
            tickets_by_status=_slices(repo.tickets_by_status()),
            tickets_by_origin=_slices(repo.tickets_by_origin()),
            actions_by_domain=_slices(repo.actions_by_domain()),
            actions_by_type=_slices(repo.actions_by_type()),
            diagnostic_by_service=_slices(repo.diagnostic_by_service()),
            top_problems=_slices(repo.top_problems()),
            top_faq_questions=_slices(repo.top_faq_questions()),
            unanswered_questions=_slices(repo.unanswered_questions()),
            timeseries=timeseries,
            inventory=StatsInventory(faq_items=faq_total, faq_published=faq_published),
        )

    def _timeseries(self, days: int) -> Tuple[StatsPeriod, List[StatsTimePoint]]:
        """La fenetre est cadree sur l'activite REELLE, pas sur `now()` : elle
        se termine a la derniere trace enregistree et ne remonte jamais avant
        la premiere. Une base dont la derniere ecriture date de trois semaines
        produirait sinon une courbe entierement plate a zero -- exactement le
        symptome que cette page presentait avant d'etre branchee ici. `days`
        ne fait que plafonner la profondeur de la fenetre."""
        repo = self.repository
        first, last = repo.activity_bounds()
        if first is None or last is None:
            return StatsPeriod(start=None, end=None, days=days), []

        end = last.date()
        start = max(first.date(), end - timedelta(days=days - 1))

        conversations = dict(repo.daily_conversations(start))
        tickets = dict(repo.daily_tickets(start))
        faq_lookups = dict(repo.daily_faq_lookups(start))

        points = [
            StatsTimePoint(
                date=day.isoformat(),
                conversations=_at(conversations, day),
                tickets=_at(tickets, day),
                faq_lookups=_at(faq_lookups, day),
            )
            for day in _days_between(start, end)
        ]
        return StatsPeriod(start=start.isoformat(), end=end.isoformat(), days=days), points


def _rate(numerator: int, denominator: int) -> Optional[float]:
    """None (et pas 0.0) quand il n'y a rien a mesurer : "aucune donnee" et
    "0 %" ne disent pas la meme chose sur un tableau de bord."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _slices(rows: Sequence[Tuple[str, int]]) -> List[StatSlice]:
    return [StatSlice(label=label, value=value) for label, value in rows]


def _at(counts: Dict[date, int], day: date) -> int:
    """Les jours sans activite sont absents du GROUP BY : les remettre a zero
    ici, sinon la courbe relierait deux dates non consecutives comme si
    l'intervalle n'existait pas."""
    return int(counts.get(day, 0))


def _days_between(start: date, end: date) -> List[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
