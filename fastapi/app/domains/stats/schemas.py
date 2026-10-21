from typing import List, Optional

from pydantic import BaseModel


class StatSlice(BaseModel):
    """Une ligne de repartition (categorie de ticket, domaine d'action...)."""

    label: str
    value: int


class StatsPeriod(BaseModel):
    """Fenetre reellement couverte par les series temporelles.

    `end` est la date de la DERNIERE activite enregistree, pas `now()` : une
    base dont la derniere trace date de trois semaines produirait sinon un
    graphique vide alors que les donnees existent. Les deux bornes sont
    renvoyees pour que l'interface puisse afficher la periode telle quelle,
    sans laisser croire qu'il s'agit forcement des N derniers jours.
    """

    start: Optional[str] = None
    end: Optional[str] = None
    days: int


class StatsKpis(BaseModel):
    conversations: int
    tickets_total: int
    tickets_open: int
    tickets_resolved: int
    escalations: int
    agent_actions: int
    feedback_entries: int
    ratings_total: int
    # None (et pas 0.0) quand le denominateur est vide : "aucune mesure" et
    # "0 %" ne veulent pas dire la meme chose cote interface.
    auto_resolution_rate: Optional[float] = None
    faq_answer_rate: Optional[float] = None
    satisfaction_rate: Optional[float] = None
    avg_faq_score: Optional[float] = None
    avg_latency_ms: Optional[int] = None


class StatsTimePoint(BaseModel):
    date: str
    conversations: int
    tickets: int
    faq_lookups: int


class StatsInventory(BaseModel):
    faq_items: int
    faq_published: int


class StatsOverviewResponse(BaseModel):
    generated_at: str
    period: StatsPeriod
    kpis: StatsKpis
    tickets_by_category: List[StatSlice]
    tickets_by_urgency: List[StatSlice]
    tickets_by_status: List[StatSlice]
    tickets_by_origin: List[StatSlice]
    actions_by_domain: List[StatSlice]
    actions_by_type: List[StatSlice]
    diagnostic_by_service: List[StatSlice]
    top_problems: List[StatSlice]
    top_faq_questions: List[StatSlice]
    unanswered_questions: List[StatSlice]
    timeseries: List[StatsTimePoint]
    inventory: StatsInventory
