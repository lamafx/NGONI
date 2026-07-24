"""Audit qualite du code, fonctionnalite #1 : suite de non-regression pour la
classification semantique du Diagnostic Engine.

Contexte : un audit manuel (scripts jetables, jamais committes) a decouvert
que plusieurs problemes du catalogue (wallet_stub + user_stub) partageaient
assez de vocabulaire ("compte", "bloque") pour qu'un message clairement
destine a l'un se fasse voler par un autre -- ex. "mon retrait est bloque
depuis hier" gagnait a tort vers compliance_hold_blocking avant correction
des example_phrases des manifestes concernes (voir leurs commentaires
"Audit qualite du code"). Ce fichier transforme cet audit ponctuel en garde-
fou permanent : si un futur changement de manifeste (nouvel exemple, nouvelle
description, nouveau probleme) réintroduit une collision, ce test echoue en
CI au lieu d'attendre qu'un utilisateur reel la decouvre en production.

Import DIRECT des vrais manifestes (wallet_stub.diagnostic.manifest.MANIFEST,
idem user_stub) plutot qu'une copie codee en dur ici : une copie driverait
silencieusement du contenu reellement servi des le premier changement de
manifeste sans mise a jour de ce fichier, ce qui aurait rendu ce test
inutile (il testerait un catalogue qui n'existe plus). Meme principe que
test_diagnostic_contract_conformance.py (Phase 6, etape 27).

Les messages de test sont des PARAPHRASES tenues a l'ecart des
example_phrases des manifestes (jamais copiees mot pour mot) : le but est de
verifier une generalisation reelle, pas de re-verifier qu'un exemple
retrouve son propre vecteur (ce qui serait trivialement vrai et ne
detecterait aucune regression)."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.shared.embeddings import cosine_similarity, embed_passage, embed_query  # noqa: E402
from user_stub.diagnostic.manifest import MANIFEST as USER_MANIFEST  # noqa: E402
from wallet_stub.diagnostic.manifest import MANIFEST as WALLET_MANIFEST  # noqa: E402

# Marge relative minimale entre le 1er et le 2e candidat pour considerer le
# gagnant comme non-ambigu -- memes seuils que CLASSIFICATION_RELATIVE_MARGIN
# cote rasa/actions/diagnostic.py (0.02), pas une valeur arbitraire propre a
# ce fichier.
MIN_RELATIVE_MARGIN = 0.02

# intended_problem_id -> paraphrases realistes, tenues a l'ecart des
# example_phrases des manifestes (voir docstring du module).
TEST_MESSAGES: dict[str, list[str]] = {
    "withdrawal_pending": [
        "je veux retirer de l'argent mais ça n'a jamais été crédité",
        "mon retrait ne passe pas depuis ce matin",
        "impossible de retirer mon argent, ça coince depuis hier soir",
    ],
    "topup_not_credited": [
        "j'ai fait une recharge mais mon solde n'a pas changé",
        "ma recharge n'apparaît pas sur mon compte",
        "j'ai credite mon wallet mais ca ne montre rien sur mon compte",
    ],
    "gift_not_received": [
        "j'ai envoyé un cadeau à un ami mais il dit qu'il ne l'a pas reçu",
        "le cadeau que j'ai offert n'est jamais arrivé",
    ],
    "kyc_status_issue": [
        "mon dossier d'identité est refusé, je comprends pas pourquoi",
        "ma vérification KYC est bloquée depuis des jours",
        # Regression : "Vérifie mon KYC." (rapporte comme mal classe -- voir
        # rasa/actions/diagnostic.py, _rescue_unique_keyword_match). Passe
        # deja confortablement ici (marge embedding nette) ; les relances
        # courtes qui necessitent reellement le repechage par mot-cle
        # ("kyc", "mon kyc"...) sont couvertes separement dans
        # TestKeywordRescuePreconditions ci-dessous, PAS ici -- leur marge
        # brute est trop fine pour ce test (voir son docstring).
        "Vérifie mon KYC.",
    ],
    "account_access_blocked": [
        "je n'arrive plus à me connecter à mon compte, il semble bloqué",
        "impossible d'accéder à mon compte depuis ce matin",
    ],
    "compliance_hold_blocking": [
        "je ne peux plus rien faire sur mon compte, un message parle de conformité",
        "un controle de conformite bloque mes actions",
    ],
    "account_deletion_status": [
        "j'ai supprimé mon compte par erreur et je veux le récupérer",
        "je ne sais pas où en est ma demande de suppression de compte",
    ],
    "parental_consent_status": [
        "le compte de mon fils est bloqué, on attend l'accord du parent",
        "le consentement de mes parents n'a jamais été traité",
    ],
}


def _build_catalog_embeddings() -> dict[str, list[list[float]]]:
    """(service, problem_id) -> vecteurs de reference (description + example_phrases),
    exactement la meme construction que CapabilityRegistry._compute_all_embeddings
    (registry.py), mais calculee une seule fois pour tout le module de test
    plutot qu'a chaque cas."""
    embeddings: dict[str, list[list[float]]] = {}
    for manifest in (WALLET_MANIFEST, USER_MANIFEST):
        for problem in manifest.problems:
            texts = [problem.description or problem.label, *problem.example_phrases]
            embeddings[problem.id] = [embed_passage(t) for t in texts]
    return embeddings


@pytest.fixture(scope="module")
def catalog_embeddings() -> dict[str, list[list[float]]]:
    return _build_catalog_embeddings()


def _best_score(problem_id: str, message_embedding: list[float], catalog: dict[str, list[list[float]]]) -> float:
    return max(cosine_similarity(message_embedding, vector) for vector in catalog[problem_id])


def _flat_test_cases() -> list[tuple[str, str]]:
    return [(problem_id, message) for problem_id, messages in TEST_MESSAGES.items() for message in messages]


class TestClassificationDoesNotCollide:
    @pytest.mark.parametrize("intended_problem_id,message", _flat_test_cases())
    def test_message_classifies_to_intended_problem_with_clear_margin(
        self, intended_problem_id, message, catalog_embeddings
    ):
        message_embedding = embed_query(message)
        scores = {
            problem_id: _best_score(problem_id, message_embedding, catalog_embeddings)
            for problem_id in catalog_embeddings
        }
        ranked = sorted(scores.items(), key=lambda item: -item[1])
        winner_id, winner_score = ranked[0]
        _, runner_up_score = ranked[1]
        relative_margin = (winner_score - runner_up_score) / winner_score

        assert winner_id == intended_problem_id, (
            f"{message!r} classe a tort vers {winner_id!r} (score={winner_score:.4f}) "
            f"au lieu de {intended_problem_id!r} (score={scores[intended_problem_id]:.4f}) -- "
            f"top-3 : {ranked[:3]}"
        )
        assert relative_margin >= MIN_RELATIVE_MARGIN, (
            f"{message!r} gagne vers {intended_problem_id!r} mais avec une marge trop fine "
            f"({relative_margin:.4f} < {MIN_RELATIVE_MARGIN}) face a {ranked[1][0]!r} -- "
            "risque de bascule au moindre changement de manifeste, meme si le test passe aujourd'hui"
        )


# Repli lexical cote Rasa (rasa/actions/diagnostic.py, KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY) --
# garder cette valeur synchronisee avec celle-la si l'une des deux change.
KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY = 0.78

# intended_problem_id -> relances courtes, plausibles en pratique (notamment
# comme reponse a "pouvez-vous decrire le probleme plus precisement ?"), qui
# echouent au filtre embedding normal (marge/seuil trop fins pour
# TestClassificationDoesNotCollide) mais que _rescue_unique_keyword_match doit
# repecher grace a un mot-cle unique dans le catalogue.
NEAR_MISS_MESSAGES: dict[str, list[str]] = {
    "kyc_status_issue": ["kyc", "mon kyc", "kyc svp", "check kyc", "statut kyc"],
}


def _all_problems() -> list:
    return [problem for manifest in (WALLET_MANIFEST, USER_MANIFEST) for problem in manifest.problems]


def _keyword_matches(keyword: str, message: str) -> bool:
    # Replique volontairement simplifiee de _keyword_matches cote
    # rasa/actions/diagnostic.py (correspondance mot entier, insensible a la
    # casse) : la fenetre de negation n'a pas d'utilite sur ces messages
    # courts sans negation, et ce fichier ne peut de toute facon pas importer
    # diagnostic.py (rasa_sdk n'est pas une dependance de ce venv) -- voir
    # docstring du module.
    return re.search(rf"\b{re.escape(keyword.lower())}\b", message.lower()) is not None


def _flat_near_miss_cases() -> list[tuple[str, str]]:
    return [
        (problem_id, message)
        for problem_id, messages in NEAR_MISS_MESSAGES.items()
        for message in messages
    ]


class TestKeywordRescuePreconditions:
    """Le mecanisme de repechage par mot-cle (rasa/actions/diagnostic.py,
    _rescue_unique_keyword_match) ne peut pas etre execute directement ici
    (rasa_sdk n'est pas une dependance de ce venv, voir docstring du module).
    Ces tests verifient donc, cote donnees uniquement, les DEUX preconditions
    dont ce mecanisme depend pour chaque relance courte du tableau ci-dessus :
    un mot-cle qui la matche est UNIQUE dans tout le catalogue, et son
    meilleur score embedding reste au-dessus du plancher de repechage. Un
    futur changement de manifeste qui romprait l'une des deux ferait echouer
    ce test en CI, avant qu'un utilisateur ne revive le bug KYC corrige."""

    @pytest.mark.parametrize("intended_problem_id,message", _flat_near_miss_cases())
    def test_near_miss_message_has_unique_keyword_match(self, intended_problem_id, message):
        problems = _all_problems()
        matching = [
            problem
            for problem in problems
            if any(_keyword_matches(kw, message) for kw in problem.keywords)
        ]
        matching_ids = [p.id for p in matching]
        assert matching_ids == [intended_problem_id], (
            f"{message!r} devrait matcher un mot-cle UNIQUEMENT pour {intended_problem_id!r}, "
            f"mais matche : {matching_ids!r} -- le repechage par mot-cle refuserait de promouvoir "
            "ce message (ambiguite, voir _rescue_unique_keyword_match)"
        )

    @pytest.mark.parametrize("intended_problem_id,message", _flat_near_miss_cases())
    def test_near_miss_message_stays_above_rescue_floor(
        self, intended_problem_id, message, catalog_embeddings
    ):
        message_embedding = embed_query(message)
        score = _best_score(intended_problem_id, message_embedding, catalog_embeddings)
        assert score >= KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY, (
            f"{message!r} : meilleur score pour {intended_problem_id!r} = {score:.4f}, "
            f"sous le plancher de repechage {KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY} -- "
            "_rescue_unique_keyword_match ne le promouvrait plus"
        )
