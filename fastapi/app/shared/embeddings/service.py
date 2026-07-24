"""Service d'embeddings partage par toute la plateforme (FAQ, diagnostic...).

Un seul modele charge par process FastAPI (singleton), reutilise par tous les
domaines qui ont besoin de similarite semantique -- evite de dupliquer un
modele de plusieurs centaines de Mo dans chaque conteneur qui en aurait
besoin (voir router.py : POST /embeddings/query, appele par Rasa, plutot que
de charger ce modele une 2e fois dans le conteneur actions).
"""

import os
from typing import List

import torch
from sentence_transformers import SentenceTransformer

# Bascule e5-small -> e5-base (2026-07) : mesure empirique sur le catalogue
# reel (8 problemes wallet+user, 20 phrases hors-sujet, 59 paraphrases
# leave-one-out) a e5-small un taux de FAUX POSITIFS de 65% au seuil de
# classification diagnostic (0.83) -- une simple salutation ("Bonsoir
# comment allez-vous ?") ou un "Merci beaucoup" declenchaient un probleme
# diagnostic au hasard. e5-base (meme famille/convention query:/passage:,
# juste plus de parametres) descend ce taux a 10% ET ameliore le rappel
# (66% -> 76%) sur le MEME seuil -- gain net, pas un compromis. Voir
# MIN_EMBEDDING_SIMILARITY (rasa/actions/diagnostic.py) et DEFAULT_THRESHOLD
# (app/domains/faq/service.py), recalibres pour ce nouveau modele.
#
# Consequence : dimension d'embedding passee de 384 a 768 (voir
# app/domains/faq/models.py, core.faq_items.embedding) -- les vecteurs
# stockes en base NE SONT PAS reutilisables tels quels, ils ont ete
# recalcules avec ce modele (voir scripts/reembed_faq.py). Un changement de
# modele futur devra refaire le meme exercice : deux vecteurs ne sont
# comparables que s'ils viennent du meme modele.
MODEL_NAME = "intfloat/multilingual-e5-base"


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
    # Convention des modeles E5 : prefixer differemment une requete de
    # recherche ("query: ") et un document/passage compare ("passage: ") --
    # necessaire pour de bons resultats avec cette famille de modeles. Oublier
    # ce prefixe degrade sensiblement la qualite de la similarite.
    model = get_embedding_model()
    return model.encode(f"query: {text}", convert_to_numpy=True, normalize_embeddings=True).tolist()


def embed_query_batch(texts: List[str]) -> List[List[float]]:
    # Un seul appel a `model.encode` sur toute la liste plutot qu'un appel
    # par texte : sentence-transformers encode le lot en un seul forward pass
    # vectorise, bien plus efficace que N appels HTTP separes -- utilise par
    # Rasa pour scorer plusieurs segments/clauses d'un meme message
    # (audit qualite du code, cas #4) sans multiplier les aller-retours reseau.
    model = get_embedding_model()
    embeddings = model.encode(
        [f"query: {text}" for text in texts], convert_to_numpy=True, normalize_embeddings=True
    )
    return embeddings.tolist()


def embed_passage(text: str) -> List[float]:
    model = get_embedding_model()
    return model.encode(f"passage: {text}", convert_to_numpy=True, normalize_embeddings=True).tolist()


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
    embeddings = model.encode(
        [f"passage: {text}" for text in texts], convert_to_numpy=True, normalize_embeddings=True
    )
    return embeddings.tolist()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    # Les deux vecteurs sont deja normalises (normalize_embeddings=True) : le
    # produit scalaire EST la similarite cosinus, pas besoin de diviser par
    # les normes.
    return float(sum(x * y for x, y in zip(a, b)))
