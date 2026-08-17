"""Service d'embeddings partage par toute la plateforme (FAQ, diagnostic...).

Un seul modele charge par process FastAPI (singleton), reutilise par tous les
domaines qui ont besoin de similarite semantique -- evite de dupliquer un
modele de plusieurs centaines de Mo dans chaque conteneur qui en aurait
besoin (voir router.py : POST /embeddings/query, appele par Rasa, plutot que
de charger ce modele une 2e fois dans le conteneur actions).
"""

import os
from pathlib import Path
from typing import List

import torch

# BAAI/bge-m3 est deja telecharge sur disque pour l'atelier d'entrainement
# BGE-M3 (voir rasa/nlu_bge/embed.py) -- pointer HF_HOME vers le MEME cache
# ici evite un 2e telechargement (~2 Go) dans le cache par defaut
# (~/.cache/huggingface) rien que pour ce process FastAPI. Doit etre pose
# AVANT le premier import de sentence_transformers/huggingface_hub (lu une
# seule fois a l'initialisation de la lib).
_REPO_ROOT = Path(__file__).resolve().parents[4]
os.environ.setdefault("HF_HOME", str(_REPO_ROOT / "rasa" / ".cache" / "huggingface"))

from sentence_transformers import SentenceTransformer  # noqa: E402

# Bascule e5-base -> BGE-M3 (2026-07) : unifie sur le MEME modele que celui
# utilise par les classifieurs d'intention BGE-M3 (voir
# rasa/nlu_bge/embed.py et app/domains/nlu/) -- un seul modele d'embedding
# pour toute la plateforme (FAQ, diagnostic, NLU), au lieu de deux copies
# differentes (e5-base ici, BGE-M3 cote nlu_bge) qui n'auraient jamais pu
# partager le moindre vecteur. BGE-M3 ne suit pas la convention E5
# query:/passage: (voir rasa/nlu_bge/embed.py, aucun prefixe) -- encode()
# est appele directement sur le texte brut ci-dessous.
#
# Consequence : dimension d'embedding passee de 768 (e5-base) a 1024
# (voir app/domains/faq/models.py, ia.faq_items.embedding) -- les vecteurs
# stockes en base NE SONT PAS reutilisables tels quels, recalcules avec ce
# modele (voir scripts/reembed_faq.py, migrations/0013_bge_m3_upgrade.sql).
#
# ATTENTION calibration : MIN_EMBEDDING_SIMILARITY (rasa/actions/diagnostic.py)
# et DEFAULT_THRESHOLD/SECONDARY_THRESHOLD/DUPLICATE_THRESHOLD
# (app/domains/faq/service.py) avaient ete mesures sur la distribution de
# scores d'e5-base -- BGE-M3 produit une distribution differente. Reportes
# tels quels pour ce changement (pas de corpus de recalibration dedie
# disponible), a revalider en priorite si la FAQ ou le diagnostic montrent
# trop de faux positifs/negatifs en usage reel.
MODEL_NAME = "BAAI/bge-m3"


def get_embedding_model() -> SentenceTransformer:
    if not hasattr(get_embedding_model, "model"):
        # Constate en pratique (2026-07) : torch ne se limitait qu'a 2 threads
        # sur les 4 coeurs logiques disponibles sur cette machine, en dessous
        # de ce que os.cpu_count() permettrait -- change quasi gratuitement le
        # temps d'un encode() CPU (pas de GPU disponible ici, voir
        # torch.cuda.is_available()). Positionne avant le premier encode(),
        # sans effet une fois des operations tensorielles deja lancees.
        torch.set_num_threads(os.cpu_count() or 1)
        get_embedding_model.model = SentenceTransformer(MODEL_NAME)
    return get_embedding_model.model


def embed_query(text: str) -> List[float]:
    # BGE-M3 (contrairement a la famille E5) n'a pas besoin de prefixe
    # query:/passage: distinct -- meme fonction d'encodage des deux cotes
    # (voir rasa/nlu_bge/embed.py, seul point de reference BGE-M3 deja
    # eprouve dans ce projet). embed_query/embed_passage restent deux
    # fonctions separees pour ne rien changer a la signature des appelants
    # (app/domains/faq/service.py, app/domains/diagnostic/registry.py).
    model = get_embedding_model()
    return model.encode(text, convert_to_numpy=True, normalize_embeddings=True).tolist()


def embed_query_batch(texts: List[str]) -> List[List[float]]:
    # Un seul appel a `model.encode` sur toute la liste plutot qu'un appel
    # par texte : sentence-transformers encode le lot en un seul forward pass
    # vectorise, bien plus efficace que N appels HTTP separes -- utilise par
    # Rasa pour scorer plusieurs segments/clauses d'un meme message
    # (audit qualite du code, cas #4) sans multiplier les aller-retours reseau.
    model = get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return embeddings.tolist()


def embed_passage(text: str) -> List[float]:
    model = get_embedding_model()
    return model.encode(text, convert_to_numpy=True, normalize_embeddings=True).tolist()


def embed_passage_batch(texts: List[str]) -> List[List[float]]:
    # Meme principe que embed_query_batch : un seul forward pass pour tout le
    # lot. Introduit pour CapabilityRegistry.refresh() (voir
    # app/domains/diagnostic/registry.py), qui appelait auparavant
    # embed_passage() UNE FOIS PAR PHRASE (~67 appels par cycle de
    # rafraichissement avec le catalogue actuel) au lieu d'un seul appel
    # batche.
    if not texts:
        return []
    model = get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return embeddings.tolist()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    # Les deux vecteurs sont deja normalises (normalize_embeddings=True) : le
    # produit scalaire EST la similarite cosinus, pas besoin de diviser par
    # les normes.
    return float(sum(x * y for x, y in zip(a, b)))
