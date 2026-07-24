"""Tests de FaqService (recherche hybride, Top-3, garde-fou anti-doublon --
docs/16-audit-faq-nlu-2026-07.md 16.6, docs/taches.txt P1/P2) avec un faux
FaqRepository en memoire -- meme convention que
tests/test_diagnostic_audit_repository.py (FakeDiagnosticDBSession) : ces
tests verifient la LOGIQUE de scoring/decision, pas la requete pgvector
reelle (voir tests/test_faq_repository.py pour celle-ci, contre une vraie
base). Les scores "semantiques" ci-dessous sont fournis directement (pas
calcules par un vrai embedding) : embed_query/embed_passage sont mockees
pour que ces tests restent rapides et deterministes, independants du modele
intfloat/multilingual-e5-base."""

import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.faq.models import FaqCategory, FaqItem, FaqStatus  # noqa: E402
from app.domains.faq.schemas import FaqCreate  # noqa: E402
from app.domains.faq.service import DEFAULT_THRESHOLD, DUPLICATE_THRESHOLD, SECONDARY_THRESHOLD, FaqService  # noqa: E402


def _make_item(question: str, slug: str, keywords=None, answer: str = "réponse") -> FaqItem:
    return FaqItem(
        question=question,
        answer=answer,
        category=FaqCategory.GENERAL,
        keywords=keywords or [],
        slug=slug,
        status=FaqStatus.PUBLISHED,
        locale="fr",
    )


class FakeFaqRepository:
    """N'implemente que l'API reellement utilisee par FaqService. `candidates`
    simule ce que pgvector aurait renvoye (deja trie par score semantique
    brut) -- find_top_k/find_closest ne font qu'y piocher, sans jamais
    interpreter `embedding` (mocke dans les tests, voir ci-dessous)."""

    def __init__(self, candidates: List[Tuple[FaqItem, float]]) -> None:
        self._candidates = candidates
        self.added: List[FaqItem] = []

    def find_top_k(self, embedding, k: int, locale: str = "fr"):
        return self._candidates[:k]

    def find_closest(self, embedding, locale: str = "fr"):
        return self._candidates[0] if self._candidates else None

    def add(self, item: FaqItem) -> FaqItem:
        self.added.append(item)
        return item

    def find_by_slug(self, slug: str) -> Optional[FaqItem]:
        for item, _ in self._candidates:
            if item.slug == slug:
                return item
        return None


def _service_with(monkeypatch, candidates: List[Tuple[FaqItem, float]]) -> FaqService:
    monkeypatch.setattr("app.domains.faq.service.embed_query", lambda text: [0.0])
    monkeypatch.setattr("app.domains.faq.service.embed_passage", lambda text: [0.0])
    return FaqService(FakeFaqRepository(candidates))


# --- Recherche hybride (audit FAQ #7) ---

def test_keyword_boost_rescues_candidate_below_threshold(monkeypatch):
    # Cas reellement observe (voir docs/20-*, verification manuelle) : score
    # semantique seul sous DEFAULT_THRESHOLD, mais le mot-cle "wallet" est
    # present dans la question posee -- le boost doit faire franchir le seuil.
    item = _make_item("Comment fonctionnent les pièces NGONI ?", "fonctionnement-pieces", keywords=["pièces", "wallet"])
    semantic_score = DEFAULT_THRESHOLD - 0.01
    service = _service_with(monkeypatch, [(item, semantic_score)])

    result = service.find_best_answer("des questions sur mon wallet", locale="fr")

    assert result is not None
    assert result.question == item.question
    assert result.score > semantic_score


def test_no_keyword_match_leaves_score_unchanged_below_threshold(monkeypatch):
    item = _make_item("Comment fonctionnent les pièces NGONI ?", "fonctionnement-pieces", keywords=["pièces", "wallet"])
    semantic_score = DEFAULT_THRESHOLD - 0.01
    service = _service_with(monkeypatch, [(item, semantic_score)])

    result = service.find_best_answer("une question totalement différente", locale="fr")

    assert result is None


def test_keyword_boost_is_capped(monkeypatch):
    # Beaucoup de mots-cles presents a la fois : le boost ne doit jamais
    # depasser MAX_KEYWORD_BOOST (score plafonne a 1.0 par ailleurs).
    item = _make_item(
        "Quels sont les moyens de paiement disponibles ?",
        "moyens-paiement",
        keywords=["paiement", "payer", "orange money", "mtn money", "wave", "visa"],
    )
    service = _service_with(monkeypatch, [(item, 0.80)])

    result = service.find_best_answer("paiement payer orange money mtn money wave visa", locale="fr")

    assert result is not None
    assert result.score <= 0.80 + 0.05 + 1e-9  # MAX_KEYWORD_BOOST = 0.05


def test_find_best_answer_returns_none_when_no_candidate(monkeypatch):
    service = _service_with(monkeypatch, [])
    assert service.find_best_answer("n'importe quoi", locale="fr") is None


# --- Top-3 / "vouliez-vous dire..." (audit FAQ #8) ---

def test_find_top_matches_filters_by_secondary_threshold(monkeypatch):
    below = _make_item("Question hors-sujet", "hors-sujet")
    matching_low = _make_item("Comment retirer mes revenus ?", "retirer-revenus")
    matching_high = _make_item("Combien de temps prend un retrait ?", "delai-retrait")
    candidates = [
        (matching_high, SECONDARY_THRESHOLD + 0.05),
        (matching_low, SECONDARY_THRESHOLD + 0.01),
        (below, SECONDARY_THRESHOLD - 0.10),
    ]
    service = _service_with(monkeypatch, candidates)

    matches = service.find_top_matches("cmt on retire largent", locale="fr", k=3)

    assert [m.slug for m in matches] == ["delai-retrait", "retirer-revenus"]
    assert all(m.score >= SECONDARY_THRESHOLD for m in matches)


def test_find_top_matches_respects_k(monkeypatch):
    items = [_make_item(f"Question {i}", f"slug-{i}") for i in range(5)]
    candidates = [(item, SECONDARY_THRESHOLD + 0.1) for item in items]
    service = _service_with(monkeypatch, candidates)

    matches = service.find_top_matches("question", locale="fr", k=3)

    assert len(matches) == 3


def test_find_top_matches_empty_when_nothing_clears_secondary_threshold(monkeypatch):
    item = _make_item("Question hors-sujet", "hors-sujet")
    service = _service_with(monkeypatch, [(item, SECONDARY_THRESHOLD - 0.2)])

    assert service.find_top_matches("n'importe quoi", locale="fr") == []


# --- Garde-fou anti-doublon a l'ecriture (audit FAQ #9) ---

def test_add_faq_skips_near_duplicate(monkeypatch):
    existing = _make_item("Comment acheter des pièces NGONI ?", "acheter-pieces-ngoni")
    service = _service_with(monkeypatch, [(existing, DUPLICATE_THRESHOLD + 0.01)])

    result = service.add_faq(FaqCreate(question="Comment acheter des pieces NGONI ?", answer="x", category=FaqCategory.COINS))

    assert result is existing
    assert service.repository.added == []  # aucune insertion


def test_add_faq_inserts_when_not_a_duplicate(monkeypatch):
    existing = _make_item("Comment acheter des pièces NGONI ?", "acheter-pieces-ngoni")
    service = _service_with(monkeypatch, [(existing, DUPLICATE_THRESHOLD - 0.10)])

    result = service.add_faq(FaqCreate(question="Une toute autre question ?", answer="x", category=FaqCategory.GENERAL))

    assert result is not existing
    assert len(service.repository.added) == 1
    assert service.repository.added[0].question == "Une toute autre question ?"


def test_add_faq_inserts_when_catalog_empty(monkeypatch):
    service = _service_with(monkeypatch, [])

    result = service.add_faq(FaqCreate(question="Première question ?", answer="x", category=FaqCategory.GENERAL))

    assert len(service.repository.added) == 1
    assert result.question == "Première question ?"
