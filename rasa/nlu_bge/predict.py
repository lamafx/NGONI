"""Point d'entree NLU principal (config A) :

    message -> pretraitement texte -> embedding BGE-M3 -> classifieur -> intention + confiance

Charge le classifieur entraine par train.py (rasa/nlu_bge/model/).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import joblib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import normalize_text  # noqa: E402
from embed import embed_one  # noqa: E402

MODEL_DIR = Path(__file__).resolve().parent / "model"

_classifier = None
_label_encoder = None
_loaded = False


def _load_artifacts():
    global _classifier, _label_encoder, _loaded
    if _loaded or (_classifier is not None and _label_encoder is not None):
        _loaded = True
        return _classifier, _label_encoder

    if not (MODEL_DIR / "classifier.joblib").exists():
        raise FileNotFoundError(
            f"Aucun modele entraine dans {MODEL_DIR} -- lancer train.py d'abord."
        )

    _classifier = joblib.load(MODEL_DIR / "classifier.joblib")
    _label_encoder = joblib.load(MODEL_DIR / "label_encoder.joblib")
    _loaded = True
    return _classifier, _label_encoder


def predict(text: str, top_k: int = 3) -> Dict:
    """Retourne {"text", "intent", "confidence", "top_k": [...]}"""
    clf, encoder = _load_artifacts()
    clean_text = normalize_text(text)
    vector = embed_one(clean_text).reshape(1, -1)

    if hasattr(clf, "predict_proba"):
        proba = clf.predict_proba(vector)[0]
    else:
        # decision_function fallback (ex. classifieurs sans predict_proba) :
        # normalise en pseudo-probabilites via softmax.
        import numpy as np

        scores = clf.decision_function(vector)[0]
        exp = np.exp(scores - scores.max())
        proba = exp / exp.sum()

    order = proba.argsort()[::-1]
    top = [
        {"intent": encoder.inverse_transform([idx])[0], "confidence": float(proba[idx])}
        for idx in order[:top_k]
    ]
    best = top[0]
    return {
        "text": text,
        "intent": best["intent"],
        "confidence": best["confidence"],
        "top_k": top,
    }


def predict_batch(texts: List[str], top_k: int = 3) -> List[Dict]:
    return [predict(t, top_k=top_k) for t in texts]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python predict.py \"message utilisateur\"")
        sys.exit(1)
    message = " ".join(sys.argv[1:])
    result = predict(message)
    print(json.dumps(result, indent=2, ensure_ascii=False))
