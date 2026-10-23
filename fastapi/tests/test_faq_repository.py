"""Tests de FaqRepository contre une VRAIE base Postgres+pgvector -- meme
convention que tests/test_wallet_service.py (docstring : "ces tests verifient
la logique... pas la connectivite Postgres reelle... deja couverte par [des
tests qui touchent] une vraie base"). Le filtrage/tri (`ORDER BY embedding
<=> :query`) vit entierement en SQL (pgvector), impossible a verifier
utilement avec une fausse Session (voir tests/test_faq_service.py pour la
logique de scoring hybride, elle testee sans DB reelle).

Necessite : Postgres natif demarre, catalogue reel seede
(fastapi/seeds/faq_items.sql, voir son en-tete) -- exactement l'environnement
de developpement documente dans docs/10-deploiement.md, pas un mock."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.domains.faq.repository import FaqRepository  # noqa: E402
from app.shared.embeddings import embed_query  # noqa: E402

# Question reelle du catalogue seede (fastapi/seeds/faq_items.sql) -- sert de
# cas d'auto-retrouvaille : embedder EXACTEMENT cette question doit la
# retrouver en tete, avec un score tres proche de 1.0.
KNOWN_QUESTION = "Comment acheter des pièces NGONI ?"
KNOWN_SLUG = "acheter-pieces-ngoni"


@pytest.fixture(scope="module")
def repository():
    session = SessionLocal()
    try:
        yield FaqRepository(session)
    finally:
        session.close()


def test_find_by_slug_returns_known_item(repository):
    item = repository.find_by_slug(KNOWN_SLUG)

    assert item is not None
    assert item.question == KNOWN_QUESTION


def test_find_by_slug_returns_none_for_unknown_slug(repository):
    assert repository.find_by_slug("ce-slug-n-existe-vraiment-pas") is None


def test_find_top_k_self_retrieval(repository):
    # Auto-retrouvaille : la question elle-meme, embeddee comme une requete
    # utilisateur (embed_query, asymetrique par rapport a embed_passage
    # utilise a l'ecriture -- voir app/shared/embeddings/service.py), doit
    # retrouver sa propre ligne en tete avec un score tres eleve.
    query_embedding = embed_query(KNOWN_QUESTION)

    results = repository.find_top_k(query_embedding, k=3, locale="fr")

    assert len(results) == 3
    top_item, top_score = results[0]
    assert top_item.slug == KNOWN_SLUG
    assert top_score > 0.9
    # Trie par score decroissant.
    scores = [score for _, score in results]
    assert scores == sorted(scores, reverse=True)


def test_find_closest_matches_first_of_find_top_k(repository):
    query_embedding = embed_query(KNOWN_QUESTION)

    closest = repository.find_closest(query_embedding, locale="fr")
    top_k = repository.find_top_k(query_embedding, k=1, locale="fr")

    assert closest is not None
    assert closest[0].slug == top_k[0][0].slug
    assert closest[1] == pytest.approx(top_k[0][1])


def test_find_top_k_filters_by_locale(repository):
    query_embedding = embed_query(KNOWN_QUESTION)

    results = repository.find_top_k(query_embedding, k=5, locale="en")

    # Aucun contenu FAQ publie en anglais aujourd'hui (voir DEFAULT_LOCALE,
    # service.py) -- catalogue reel exclusivement "fr".
    assert results == []
