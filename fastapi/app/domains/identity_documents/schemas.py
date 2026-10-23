from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentAnalysisRequest(BaseModel):
    # Image en base64 (data URL acceptee) -- JSON plutot que multipart : le
    # moteur n'embarque pas python-multipart, et une piece d'identite tient
    # largement sous la limite (8 Mo, voir router.py).
    filename: Optional[str] = Field(default=None, max_length=255)
    content_type: Optional[str] = Field(default=None, max_length=100)
    data_base64: str = Field(min_length=1, max_length=12 * 1024 * 1024)


class DocumentField(BaseModel):
    key: str
    label: str
    value: str


class DocumentCheck(BaseModel):
    label: str
    value: str
    ok: bool


class DocumentAnalysisResponse(BaseModel):
    accepted: bool
    # national_id | passport | None (fichier non adapte)
    document_type: Optional[str] = None
    document_label: Optional[str] = None
    # Pourquoi le fichier est refuse -- None quand il est accepte.
    reason: Optional[str] = None
    # Phrase prete a afficher a l'usager.
    message: str
    fields: List[DocumentField] = Field(default_factory=list)
    checks: List[DocumentCheck] = Field(default_factory=list)
    mrz_valid: Optional[bool] = None
    latency_ms: int = 0
