"""Service d'embeddings partage par toute la plateforme (FAQ, diagnostic...).

Un seul point d'entree HTTP par process FastAPI (pas de modele charge en
memoire ici) -- reutilise par tous les domaines qui ont besoin de similarite
semantique (voir router.py : POST /embeddings/query, appele par Rasa, plutot
que de dupliquer cet appel dans le conteneur actions).

Bascule le modele precedent -> le LLM local (2026-08) : le modele tourne desormais via Ollama en
local (http://host.docker.internal:11434 depuis les conteneurs, localhost
depuis ce process qui tourne nativement sur l'hote -- voir
docs/10-deploiement.md), plutot que charge en memoire dans le process.
Meme raison que pour la classification d'intention (rasa/components/) : un seul modele local, pas de dependance a une
API IA externe tierce.

Dimension INCHANGEE (1024, comme le modele precedent) : le modele d'embeddings produit
egalement des vecteurs 1024D -- contrairement au changement un modele anterieur->le modele precedent
(768->1024, voir migrations/0013_bge_m3_upgrade.sql), aucune migration de
schema n'est necessaire ici, seulement un recalcul des valeurs
(scripts/reembed_faq.py, reutilise tel quel).

ATTENTION calibration (meme reserve que pour chaque changement de modele
precedent, voir l'historique dans app/domains/faq/service.py) :
DEFAULT_THRESHOLD/SECONDARY_THRESHOLD (FAQ) et MIN_EMBEDDING_SIMILARITY/
KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY (rasa/actions/diagnostic.py) avaient
ete mesures sur la distribution de scores du precedent modele -- le nouveau modele d'embeddings
produit une distribution differente, mesuree et recalibree provisoirement
(voir commentaires a cote de chaque seuil), meme methode que le calibrage
precedent (mesure rapide, pas un leave-one-out complet faute de corpus dedie
-- docs/16-audit-faq-nlu-2026-07.md, absent du depot).
"""

import os
from typing import List, Union

import numpy as np
import requests

# localhost quand FastAPI tourne nativement a cote d'Ollama ; sous Docker
# Compose, OLLAMA_EMBED_URL vise le service ollama (http://ollama:11434,
# voir docker-compose.yml).
OLLAMA_URL = os.getenv("OLLAMA_EMBED_URL", "http://localhost:11434/api/embed")
MODEL_NAME = "qwen3-embedding:0.6b"
EMBEDDING_DIM = 1024
REQUEST_TIMEOUT_SECONDS = 45


class _OllamaEmbeddingModel:
    """Objet retourne par get_embedding_model() -- expose une methode
    encode() compatible avec l'usage la bibliotheque d'embeddings deja fait ailleurs
    (voir app/domains/nlu/engines.py::_predict_bge_sync, seul appelant qui
    utilise .encode() directement plutot que les fonctions embed_query/
    embed_passage ci-dessous), pour ne rien casser cote appelants."""

    def encode(
        self,
        text_or_texts: Union[str, List[str]],
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
        **_kwargs,
    ) -> np.ndarray:
        single = isinstance(text_or_texts, str)
        texts = [text_or_texts] if single else list(text_or_texts)
        vectors = _embed_via_ollama(texts)
        array = np.array(vectors, dtype=np.float32)
        if normalize_embeddings:
            norms = np.linalg.norm(array, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            array = array / norms
        return array[0] if single else array


def _embed_via_ollama(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    response = requests.post(
        OLLAMA_URL,
        json={"model": MODEL_NAME, "input": texts, "keep_alive": "30m"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    embeddings = response.json()["embeddings"]
    if any(len(v) != EMBEDDING_DIM for v in embeddings):
        raise RuntimeError(
            f"Le modele d'embeddings a renvoye une dimension inattendue "
            f"(attendu {EMBEDDING_DIM}) -- verifier le modele Ollama charge."
        )
    return embeddings


def get_embedding_model() -> _OllamaEmbeddingModel:
    if not hasattr(get_embedding_model, "model"):
        get_embedding_model.model = _OllamaEmbeddingModel()
    return get_embedding_model.model


def embed_query(text: str) -> List[float]:
    #  Le modele d'embeddings, comme le precedent, n'a pas besoin de prefixe query:/
    # passage: (contrairement a e5) -- le texte est envoye tel quel.
    model = get_embedding_model()
    return model.encode(text, convert_to_numpy=True, normalize_embeddings=True).tolist()


def embed_query_batch(texts: List[str]) -> List[List[float]]:
    # Un seul appel HTTP pour tout le lot : c'est le comportement natif de
    # /api/embed d'Ollama, qui accepte nativement une liste ; meme principe
    # que le batch la bibliotheque d'embeddings precedent, sans boucle cote client.
    model = get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return embeddings.tolist()


def embed_passage(text: str) -> List[float]:
    model = get_embedding_model()
    return model.encode(text, convert_to_numpy=True, normalize_embeddings=True).tolist()


def embed_passage_batch(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    model = get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return embeddings.tolist()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))
