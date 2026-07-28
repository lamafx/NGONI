"""Chargement singleton de BGE-M3 (BAAI/bge-m3) et calcul d'embeddings de
phrase. Meme esprit que fastapi/app/shared/embeddings/service.py (singleton,
CPU, sentence-transformers) mais module independant : le conteneur `rasa`
n'a pas acces au service FastAPI partage (voir plan), ce module tourne donc
avec sa propre copie du modele.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Optional

import numpy as np

MODEL_NAME = "BAAI/bge-m3"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = REPO_ROOT / "rasa" / ".cache" / "huggingface"

os.environ.setdefault("HF_HOME", str(DEFAULT_CACHE_DIR))

_model: Optional["SentenceTransformer"] = None  # type: ignore[name-defined]
_load_seconds: Optional[float] = None


def get_model():
    global _model, _load_seconds
    if _model is None:
        from sentence_transformers import SentenceTransformer

        start = time.perf_counter()
        _model = SentenceTransformer(MODEL_NAME, device="cpu")
        _load_seconds = time.perf_counter() - start
    return _model


def embed(texts: List[str], batch_size: int = 32) -> np.ndarray:
    """Vecteurs denses normalises (L2) -- la similarite cosinus devient un
    simple produit scalaire, cf. fastapi/app/shared/embeddings/service.py."""
    if not texts:
        return np.zeros((0, 1024), dtype=np.float32)
    model = get_model()
    return model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 200,
    )


def embed_one(text: str) -> np.ndarray:
    return embed([text])[0]
