"""Evaluation du pipeline BGE-M3 + classifieur sur les deux jeux de test du
projet (rasa/tests/test_nlu.yml, rasa/tests/test_nlu_adversarial.yml) --
jamais sur les donnees d'entrainement elles-memes (cf. docs/taches.txt P0#3,
"jeu de test trop proche du style d'entrainement = accuracy illusoire").

Produit : accuracy, precision/recall/F1 (macro + par intention), matrice de
confusion (CSV), liste des erreurs par intention, et un benchmark de latence
(appel unitaire non batche -- le pattern d'usage reel en production).
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, log_loss

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import load_adversarial_examples, load_test_examples, normalize_text  # noqa: E402
from embed import embed, embed_one  # noqa: E402

MODEL_DIR = Path(__file__).resolve().parent / "model"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
LATENCY_SAMPLE_SIZE = 100


def load_artifacts():
    clf = joblib.load(MODEL_DIR / "classifier.joblib")
    encoder = joblib.load(MODEL_DIR / "label_encoder.joblib")
    return clf, encoder


def predict_proba_matrix(clf, X: np.ndarray) -> np.ndarray:
    if hasattr(clf, "predict_proba"):
        return clf.predict_proba(X)
    scores = clf.decision_function(X)
    exp = np.exp(scores - scores.max(axis=1, keepdims=True))
    return exp / exp.sum(axis=1, keepdims=True)


def evaluate_split(name: str, pairs: List[Tuple[str, str]], clf, encoder) -> Dict:
    texts = [normalize_text(t) for t, _ in pairs]
    y_true_labels = [i for _, i in pairs]

    known = set(encoder.classes_)
    unknown = sorted({lbl for lbl in y_true_labels if lbl not in known})
    if unknown:
        print(f"[{name}] intentions absentes du train set, ignorees: {unknown}")
    kept = [(t, lbl) for t, lbl in zip(texts, y_true_labels) if lbl in known]
    texts = [t for t, _ in kept]
    y_true_labels = [lbl for _, lbl in kept]

    X = embed(texts)
    proba = predict_proba_matrix(clf, X)
    y_pred_idx = proba.argmax(axis=1)
    y_pred_labels = encoder.inverse_transform(y_pred_idx)
    confidences = proba.max(axis=1)

    y_true_idx = encoder.transform(y_true_labels)
    acc = accuracy_score(y_true_idx, y_pred_idx)
    ll = log_loss(y_true_idx, proba, labels=list(range(len(encoder.classes_))))

    # Macro/weighted F1 : uniquement sur les intentions reellement presentes
    # dans CE jeu de test (vraies ou predites) -- sinon une intention jamais
    # testee ici (ex. adversarial ne couvre que 9/19 intentions) compte comme
    # un 0 dans la moyenne macro alors qu'elle n'a simplement pas ete
    # mesuree, ce qui fausse artificiellement le score a la baisse.
    present_labels = sorted(set(y_true_idx) | set(y_pred_idx))
    present_names = [encoder.classes_[i] for i in present_labels]
    report = classification_report(
        y_true_idx, y_pred_idx, target_names=present_names,
        labels=present_labels, output_dict=True, zero_division=0,
    )
    cm = confusion_matrix(y_true_idx, y_pred_idx, labels=list(range(len(encoder.classes_))))

    RESULTS_DIR.mkdir(exist_ok=True)

    # Matrice de confusion en CSV
    cm_path = RESULTS_DIR / f"confusion_matrix_{name}.csv"
    with cm_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["true\\pred"] + list(encoder.classes_))
        for label, row in zip(encoder.classes_, cm):
            writer.writerow([label] + list(row))

    # Erreurs par intention
    errors_path = RESULTS_DIR / f"errors_{name}.csv"
    with errors_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "true_intent", "predicted_intent", "confidence"])
        for text, true_lbl, pred_lbl, conf in zip(texts, y_true_labels, y_pred_labels, confidences):
            if true_lbl != pred_lbl:
                writer.writerow([text, true_lbl, pred_lbl, f"{conf:.4f}"])

    report_path = RESULTS_DIR / f"report_{name}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== {name} ({len(texts)} exemples) ===")
    print(f"accuracy = {acc:.4f}")
    print(f"log loss = {ll:.4f}")
    print(f"macro F1 = {report['macro avg']['f1-score']:.4f}")
    print(f"weighted F1 = {report['weighted avg']['f1-score']:.4f}")
    n_errors = sum(1 for t, p in zip(y_true_labels, y_pred_labels) if t != p)
    print(f"erreurs : {n_errors}/{len(texts)}")
    print(f"-> {cm_path.name}, {errors_path.name}, {report_path.name}")

    return {"accuracy": acc, "log_loss": ll, "macro_f1": report["macro avg"]["f1-score"],
             "weighted_f1": report["weighted avg"]["f1-score"], "n": len(texts), "n_errors": n_errors}


def benchmark_latency(sample_texts: List[str]) -> Dict:
    """Latence par appel UNITAIRE (embed + classification d'un seul message a
    la fois) -- le pattern d'appel reel en production, pas un batch."""
    clf, encoder = load_artifacts()
    durations_ms: List[float] = []
    for text in sample_texts:
        t0 = time.perf_counter()
        vector = embed_one(normalize_text(text)).reshape(1, -1)
        predict_proba_matrix(clf, vector)
        durations_ms.append((time.perf_counter() - t0) * 1000)

    durations_ms.sort()
    p50 = statistics.median(durations_ms)
    p95 = durations_ms[int(0.95 * len(durations_ms)) - 1]
    mean = statistics.mean(durations_ms)
    result = {"n_calls": len(durations_ms), "mean_ms": mean, "p50_ms": p50, "p95_ms": p95,
              "min_ms": durations_ms[0], "max_ms": durations_ms[-1]}
    print(f"\n=== Latence (appel unitaire, {len(durations_ms)} messages) ===")
    print(f"moyenne={mean:.1f}ms  p50={p50:.1f}ms  p95={p95:.1f}ms  "
          f"min={durations_ms[0]:.1f}ms  max={durations_ms[-1]:.1f}ms")
    return result


def main() -> None:
    clf, encoder = load_artifacts()

    test_pairs = load_test_examples()
    adversarial_pairs = load_adversarial_examples()

    summary = {}
    summary["test_nlu"] = evaluate_split("test_nlu", test_pairs, clf, encoder)
    summary["test_nlu_adversarial"] = evaluate_split("adversarial", adversarial_pairs, clf, encoder)

    latency_sample = [t for t, _ in (test_pairs + adversarial_pairs)][:LATENCY_SAMPLE_SIZE]
    summary["latency"] = benchmark_latency(latency_sample)

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nResume ecrit dans {RESULTS_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
