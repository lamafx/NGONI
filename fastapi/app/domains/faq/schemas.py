import uuid
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .models import FaqCategory, FaqStatus


class FaqCreate(BaseModel):
    question: str
    answer: str
    category: FaqCategory
    keywords: List[str] = []
    is_featured: bool = False
    sort_order: int = 0
    locale: str = "fr"
    slug: Optional[str] = None
    status: FaqStatus = FaqStatus.PUBLISHED
    show_on_mobile: bool = True
    show_on_web: bool = True


class FaqItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    answer: str
    category: FaqCategory
    keywords: List[str]
    is_featured: bool
    sort_order: int
    locale: str
    slug: str
    status: FaqStatus
    show_on_mobile: bool
    show_on_web: bool


class FaqSuggestionItem(BaseModel):
    slug: str
    question: str
    answer: str
    category: FaqCategory


class FaqCategoryGroup(BaseModel):
    category: FaqCategory
    questions: List[FaqSuggestionItem]


class FaqSuggestionsResponse(BaseModel):
    categories: List[FaqCategoryGroup]


class FaqSearchRequest(BaseModel):
    question: str


class FaqSuggestionMatch(BaseModel):
    # Candidat de clarification ("vouliez-vous dire...", audit FAQ #8) --
    # slug reutilisable directement par le meme mecanisme de bouton que
    # ActionSelectFaqQuestion (rasa/actions/faq.py), la reponse elle-meme
    # n'est envoyee qu'au clic, pas ici.
    question: str
    slug: str
    score: float


class FaqSearchFlow(BaseModel):
    route: str = "Rasa -> FastAPI"
    status: str
    note: str = ""
    matched_question: Optional[str] = None


class FaqSearchResponse(BaseModel):
    answer: Optional[str] = None
    flow: FaqSearchFlow
    # Peuple uniquement quand status="not_found" ET qu'au moins un candidat
    # franchit SECONDARY_THRESHOLD (voir FaqService.find_top_matches) --
    # liste vide dans tous les autres cas, jamais None (simplifie le cote
    # Rasa : pas de distinction a faire entre "absent" et "vide").
    suggestions: List[FaqSuggestionMatch] = []


class FaqDebugCandidate(BaseModel):
    # Audit FAQ, plan d'amelioration P1 (16.6) : "necessite d'abord d'exposer
    # le score meme sous le seuil actuel (endpoint de debug ou log) pour
    # pouvoir rejouer la courbe sans reconfigurer DEFAULT_THRESHOLD a chaque
    # essai". Ce schema (et l'endpoint qui l'utilise, POST /faq/debug/search)
    # est ce prerequis -- outillage pour une future recalibration, jamais
    # appele par Rasa en production.
    question: str
    slug: str
    semantic_score: float
    hybrid_score: float


class FaqDebugSearchResponse(BaseModel):
    candidates: List[FaqDebugCandidate]
    default_threshold: float
    secondary_threshold: float
