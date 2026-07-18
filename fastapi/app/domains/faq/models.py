import datetime
import enum
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class FaqCategory(str, enum.Enum):
    ACCOUNT = "ACCOUNT"
    WALLET = "WALLET"
    COINS = "COINS"
    VPP = "VPP"
    LPP = "LPP"
    WITHDRAWAL = "WITHDRAWAL"
    NGONI_PLUS = "NGONI_PLUS"
    KYC = "KYC"
    PARENTAL_CONTROL = "PARENTAL_CONTROL"
    GIFTS = "GIFTS"
    ASSISTANCE = "ASSISTANCE"
    GENERAL = "GENERAL"


class FaqStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class FaqItem(Base):
    __tablename__ = "faq_items"
    __table_args__ = {"schema": "core"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    category = Column(
        SAEnum(FaqCategory, name="FaqCategory", schema="core", create_type=False),
        nullable=False,
    )
    keywords = Column(ARRAY(Text), nullable=False, default=list)
    is_featured = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    locale = Column(String(5), nullable=False, default="fr")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    slug = Column(String(160), nullable=False, unique=True)
    status = Column(
        SAEnum(FaqStatus, name="FaqStatus", schema="core", create_type=False),
        nullable=False,
        default=FaqStatus.PUBLISHED,
    )
    show_on_mobile = Column(Boolean, nullable=False, default=True)
    show_on_web = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    # 768 = dimension d'intfloat/multilingual-e5-base (voir
    # app/shared/embeddings/service.py) -- etait 384 (e5-small) avant
    # migration, voir fastapi/migrations/0001_e5_base_upgrade.sql et
    # scripts/reembed_faq.py.
    embedding = Column(Vector(768), nullable=False)
