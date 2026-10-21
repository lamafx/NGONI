"""Schemas du tableau de bord d'administration (page d'accueil de l'espace
Admin), distincts de ceux de la page Statistiques (schemas.py) : ce sont deux
lectures differentes des memes tables, pas deux versions du meme objet.

Convention commune a tout ce fichier : une mesure sans denominateur vaut
None, jamais 0 -- "aucune donnee" et "zero" ne s'affichent pas pareil."""

from typing import List, Optional

from pydantic import BaseModel, Field


class KpiValue(BaseModel):
    value: Optional[float] = None
    # Variation par rapport a la periode PRECEDENTE de meme duree. None quand
    # la periode precedente est vide : afficher "+100 %" parce qu'il n'y avait
    # rien avant serait un faux signal.
    previous: Optional[float] = None
    delta_pct: Optional[float] = None


class DashboardSummaryResponse(BaseModel):
    generated_at: str
    period_days: int
    conversations_in_progress: KpiValue
    tickets_treated: KpiValue
    users_helped: KpiValue
    # Temps moyen entre un message d'usager et la premiere reponse qui suit
    # (bot OU conseiller), mesure sur conversation_messages -- pas la latence
    # des microservices, qui est une autre mesure (voir /admin/stats/overview).
    avg_response_time_ms: KpiValue
    escalation_rate: Optional[float] = None
    handled_by_agents: int = 0
    conversations_waiting: int = 0
    # Compteurs de navigation (pastilles de la barre laterale et de la
    # cloche). Renvoyes ici plutot que par quatre requetes separees depuis le
    # navigateur : ce sont quatre COUNT SQL, pas quatre listes a rapatrier.
    conversations_total: int = 0
    tickets_open: int = 0
    agents_online: int = 0
    users_total: int = 0


class VolumePoint(BaseModel):
    date: str
    label: str
    conversations: int
    messages: int


class ConversationVolumeResponse(BaseModel):
    period_days: int
    points: List[VolumePoint] = Field(default_factory=list)
    total: int = 0


class IntentSlice(BaseModel):
    intent: str
    count: int
    value_pct: float
    avg_confidence: Optional[float] = None


class IntentDistributionResponse(BaseModel):
    period_days: int
    total_messages: int
    distinct_intents: int
    categories: List[IntentSlice] = Field(default_factory=list)
    # Messages non classifies (payloads structures "/intent{...}" venant d'un
    # clic sur un bouton) : comptes a part, jamais melanges aux intentions
    # reellement predites par le NLU.
    unclassified: int = 0


class ActivityItem(BaseModel):
    at: Optional[str] = None
    kind: str
    label: str
    detail: Optional[str] = None


class RecentActivityResponse(BaseModel):
    items: List[ActivityItem] = Field(default_factory=list)


class DiagnosticRunsPoint(BaseModel):
    date: str
    runs: int
    avg_latency_ms: Optional[int] = None


class DiagnosticRunsResponse(BaseModel):
    period_days: int
    runs_total: int
    avg_latency_ms: Optional[int] = None
    by_outcome: List[dict] = Field(default_factory=list)
    points: List[DiagnosticRunsPoint] = Field(default_factory=list)


class ServiceHealth(BaseModel):
    name: str
    # 'operational' | 'degraded' | 'down' | 'unknown'
    status: str
    detail: Optional[str] = None
    latency_ms: Optional[int] = None


class SystemHealthResponse(BaseModel):
    checked_at: str
    status: str
    services: List[ServiceHealth] = Field(default_factory=list)
