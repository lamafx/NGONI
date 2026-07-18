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


class FaqSearchFlow(BaseModel):
    route: str = "Rasa -> FastAPI"
    status: str
    note: str = ""
    matched_question: Optional[str] = None


class FaqSearchResponse(BaseModel):
    answer: Optional[str] = None
    flow: FaqSearchFlow
