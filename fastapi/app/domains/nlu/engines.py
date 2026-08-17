"""Moteurs NLU interchangeables : Rasa (DIETClassifier, rasa/config.yml) et
5 classifieurs BGE-M3 (LogReg/SVM/KNN/MLP/RandomForest, entraines par
rasa/nlu_bge/train.py, artefacts dans rasa/nlu_bge/model/versions/<nom>/).

Point d'entree unique : predict(model_id, text) -> NluPrediction, quel que
soit le moteur choisi. app/main.py (/api/parse, /api/chat) et le frontend ne
connaissent jamais un moteur en particulier, seulement cette fonction et le
catalogue expose par GET /api/models (voir router.py) -- c'est la seule
chose qui varie d'un modele a l'autre dans tout le pipeline (mission #3,
uniformisation).

Ajouter un 7e modele : une entree dans ENGINES ci-dessous + ses artefacts
entraines dans rasa/nlu_bge/model/versions/<nom>/, rien d'autre.
"""

from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import joblib
import numpy as np
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

try:
    from app.shared.embeddings.service import get_embedding_model
    from app.shared.rasa_client import RASA_PARSE_URL, call_rasa_with_retry
except ImportError:  # pragma: no cover - support running as `main`
    from shared.embeddings.service import get_embedding_model
    from shared.rasa_client import RASA_PARSE_URL, call_rasa_with_retry

logger = logging.getLogger(__name__)

# rasa/nlu_bge/model/versions/{name}/ -- artefacts DEJA entraines par
# rasa/nlu_bge/train.py (classifier.joblib + label_encoder.joblib), lus ici
# en lecture seule : ce module ne reentraine jamais rien, il sert seulement
# les modeles existants. Chemin relatif depuis fastapi/ (meme convention que
# SERVICES_REGISTRY_PATH, voir app/domains/diagnostic/registry.py) --
# overridable par variable d'env pour les tests ou un deploiement qui range
# le depot autrement.
BGE_VERSIONS_DIR = Path(os.getenv(
    "BGE_NLU_MODELS_DIR",
    str(Path(__file__).resolve().parents[4] / "rasa" / "nlu_bge" / "model" / "versions"),
))

# Memes valeurs que FallbackClassifier (rasa/config.yml, threshold +
# ambiguity_threshold) -- appliquees manuellement ici pour les moteurs
# bge_sklearn, qui n'ont pas d'equivalent natif. Rasa applique deja les
# siennes en interne (voir _predict_rasa : le resultat de /model/parse est
# retourne tel quel, jamais repasse par ce filtre).
CONFIDENCE_THRESHOLD = 0.70
AMBIGUITY_THRESHOLD = 0.10
FALLBACK_INTENT = "nlu_fallback"

EngineKind = Literal["rasa", "bge_sklearn"]


@dataclass(frozen=True)
class EngineSpec:
    id: str
    label: str
    kind: EngineKind
    # Sous-dossier de BGE_VERSIONS_DIR -- uniquement pour kind="bge_sklearn".
    classifier_name: Optional[str] = None


# Registre des moteurs disponibles, dans l'ordre d'affichage souhaite cote
# frontend (voir GET /api/models, router.py).
ENGINES: dict[str, EngineSpec] = {
    "rasa": EngineSpec(id="rasa", label="Rasa (DIETClassifier)", kind="rasa"),
    "bge_logreg": EngineSpec(id="bge_logreg", label="BGE-M3 + Logistic Regression", kind="bge_sklearn", classifier_name="logreg"),
    "bge_svm": EngineSpec(id="bge_svm", label="BGE-M3 + SVM", kind="bge_sklearn", classifier_name="svm"),
    "bge_knn": EngineSpec(id="bge_knn", label="BGE-M3 + KNN", kind="bge_sklearn", classifier_name="knn"),
    "bge_mlp": EngineSpec(id="bge_mlp", label="BGE-M3 + MLP", kind="bge_sklearn", classifier_name="mlp"),
    "bge_rf": EngineSpec(id="bge_rf", label="BGE-M3 + Random Forest", kind="bge_sklearn", classifier_name="rf"),
}
DEFAULT_ENGINE = "rasa"


@dataclass(frozen=True)
class NluPrediction:
    intent: str
    confidence: float
    entities: list = field(default_factory=list)


def list_engines() -> list[EngineSpec]:
    return list(ENGINES.values())


def _normalize_text(text: str) -> str:
    # Meme pretraitement que rasa/nlu_bge/dataset.py::normalize_text --
    # duplique volontairement en 2 lignes plutot que d'importer a travers la
    # frontiere fastapi/ <-> rasa/ au runtime (meme choix, et pour la meme
    # raison, que rasa/nlu_bge/embed.py : chaque process garde sa propre
    # copie des utilitaires dont il a besoin).
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip()


# {classifier_name: (clf, label_encoder)} -- charge paresseusement, une
# seule fois par variante effectivement selectionnee (jamais les 5 au
# demarrage : un seul modele est actif a la fois cote utilisateur).
_bge_classifiers: dict[str, tuple] = {}


def _load_bge_classifier(classifier_name: str):
    if classifier_name in _bge_classifiers:
        return _bge_classifiers[classifier_name]

    version_dir = BGE_VERSIONS_DIR / classifier_name
    clf_path = version_dir / "classifier.joblib"
    encoder_path = version_dir / "label_encoder.joblib"
    if not clf_path.exists() or not encoder_path.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Modele '{classifier_name}' introuvable dans {version_dir} -- "
                "lancer rasa/nlu_bge/train.py d'abord."
            ),
        )
    clf = joblib.load(clf_path)
    encoder = joblib.load(encoder_path)
    _bge_classifiers[classifier_name] = (clf, encoder)
    logger.info("[NLU] Classifieur BGE-M3 '%s' charge depuis %s", classifier_name, version_dir)
    return clf, encoder


def _predict_bge_sync(classifier_name: str, text: str) -> NluPrediction:
    """Fonction synchrone (embedding + inference sklearn, CPU-bound) --
    toujours appelee via run_in_threadpool (voir predict() ci-dessous), meme
    raison que faq_service.find_best_answer dans app/main.py : ne jamais
    bloquer la boucle asyncio du process FastAPI."""
    clf, encoder = _load_bge_classifier(classifier_name)
    clean_text = _normalize_text(text)
    model = get_embedding_model()
    vector = model.encode(clean_text, convert_to_numpy=True, normalize_embeddings=True).reshape(1, -1)

    if hasattr(clf, "predict_proba"):
        proba = clf.predict_proba(vector)[0]
    else:
        # decision_function fallback (ex. SVC sans probability=True) --
        # normalise en pseudo-probabilites via softmax, meme logique que
        # rasa/nlu_bge/predict.py.
        scores = clf.decision_function(vector)[0]
        exp = np.exp(scores - scores.max())
        proba = exp / exp.sum()

    order = proba.argsort()[::-1]
    top1_idx = int(order[0])
    intent = str(encoder.inverse_transform([top1_idx])[0])
    confidence = float(proba[top1_idx])

    # Fallback manuel (seuil de confiance + ambiguite) : Rasa a son propre
    # FallbackClassifier, ces classifieurs sklearn n'en ont pas -- voir
    # CONFIDENCE_THRESHOLD/AMBIGUITY_THRESHOLD ci-dessus.
    ambiguous = len(order) > 1 and (confidence - float(proba[int(order[1])])) < AMBIGUITY_THRESHOLD
    if confidence < CONFIDENCE_THRESHOLD or ambiguous:
        intent = FALLBACK_INTENT

    return NluPrediction(intent=intent, confidence=confidence, entities=[])


async def _predict_rasa(text: str) -> NluPrediction:
    response = await call_rasa_with_retry(RASA_PARSE_URL, {"text": text})
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    intent_data = (data or {}).get("intent") or {}
    return NluPrediction(
        intent=intent_data.get("name") or FALLBACK_INTENT,
        confidence=float(intent_data.get("confidence") or 0.0),
        entities=(data or {}).get("entities") or [],
    )


# Cache tres court terme {(model_id, text): (pose_a, prediction)} -- chaque
# message utilisateur declenche AUJOURD'HUI deux appels a predict() avec le
# meme (model_id, text) : /api/parse (affichage intent/confidence) puis
# /api/chat (raccourci ask_faq), quelques dizaines de ms plus tard (voir
# frontend/pages/chat/chat.controller.js::handleOutgoing). Mesure en
# pratique (2026-07-30) : l'encodage BGE-M3 domine tout le cout d'une
# prediction (~90%+, largement devant l'inference sklearn qui suit) --
# recalculer deux fois le MEME embedding pour le MEME texte double ce cout
# deja dominant pour rien. TTL volontairement tres court (quelques secondes) :
# ce cache n'a pas vocation a servir de cache general de reponses NLU
# (un meme texte reclassifie plus tard, ex. relance identique par
# l'utilisateur, doit repasser par le modele), seulement a couvrir la
# fenetre parse -> chat d'UN SEUL tour de conversation. Process unique/mono-
# worker deja suppose ailleurs (voir app/main.py, avertissement WEB_CONCURRENCY) :
# un simple dict est donc suffisant, pas besoin de verrou.
_PREDICTION_CACHE_TTL_SECONDS = 10.0
_prediction_cache: dict[tuple[str, str], tuple[float, NluPrediction]] = {}


def _prune_prediction_cache(now: float) -> None:
    expired = [key for key, (inserted_at, _) in _prediction_cache.items() if now - inserted_at > _PREDICTION_CACHE_TTL_SECONDS]
    for key in expired:
        del _prediction_cache[key]


async def predict(model_id: str, text: str) -> NluPrediction:
    """Point d'entree unique du selecteur de modele : quel que soit
    `model_id` (voir ENGINES), retourne {intent, confidence, entities} dans
    le meme format. C'est le SEUL endroit de app/main.py qui varie selon le
    modele choisi -- pilote l'intention/confiance affichees (/api/parse) et
    le raccourci ask_faq (/api/chat) ; le webhook Rasa (Core, formulaires,
    actions) recoit toujours le texte brut et gere la conversation avec sa
    propre analyse, voir le commentaire dans send_to_bot (app/main.py) pour
    la raison (regression constatee empiriquement sur le formulaire de
    reclamation en injectant une intention synthetique a la place)."""
    spec = ENGINES.get(model_id)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"Modele NLU inconnu: {model_id!r}. Voir GET /api/models.")

    now = time.monotonic()
    cache_key = (model_id, text)
    cached = _prediction_cache.get(cache_key)
    if cached is not None and now - cached[0] <= _PREDICTION_CACHE_TTL_SECONDS:
        return cached[1]

    if spec.kind == "rasa":
        prediction = await _predict_rasa(text)
    else:
        assert spec.classifier_name is not None
        prediction = await run_in_threadpool(_predict_bge_sync, spec.classifier_name, text)

    _prune_prediction_cache(now)
    _prediction_cache[cache_key] = (now, prediction)
    return prediction
