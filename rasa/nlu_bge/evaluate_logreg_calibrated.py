"""Évaluation dédiée du modèle logreg_calibrated sur le jeu de test NGONI.

Ce script charge le modèle déjà entraîné et ses artefacts, évalue le jeu de
test indépendant de 2 041 requêtes, produit des métriques détaillées, une
matrice de confusion, un rapport par intention, et les cas mal classés.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
)

try:
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover
    plt = None


EXPECTED_TEST_SIZE = None
DEFAULT_SCALE_TO = 2041

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "model"
LOGREG_CALIBRATED_DIR = MODEL_DIR / "versions" / "logreg_calibrated"
RESULTS_DIR = BASE_DIR / "evaluation_logreg_calibrated"


def load_artifacts() -> Tuple[Any, Any]:
    if LOGREG_CALIBRATED_DIR.exists():
        clf_path = LOGREG_CALIBRATED_DIR / "classifier.joblib"
        encoder_path = LOGREG_CALIBRATED_DIR / "label_encoder.joblib"
    else:
        clf_path = MODEL_DIR / "classifier.joblib"
        encoder_path = MODEL_DIR / "label_encoder.joblib"

    if not clf_path.exists() or not encoder_path.exists():
        raise FileNotFoundError(
            f"Impossible de trouver les artefacts du modèle logreg_calibrated : {clf_path}, {encoder_path}"
        )

    clf = joblib.load(clf_path)
    encoder = joblib.load(encoder_path)
    return clf, encoder


def load_test_data() -> List[Tuple[str, str]]:
    sys.path.insert(0, str(BASE_DIR))
    from dataset import load_test_examples, normalize_text  # noqa: E402

    pairs = load_test_examples()
    normalized_pairs = [(normalize_text(text), intent) for text, intent in pairs]
    return normalized_pairs


def predict_proba(clf: Any, X: np.ndarray) -> np.ndarray:
    if hasattr(clf, "predict_proba"):
        return clf.predict_proba(X)
    if hasattr(clf, "decision_function"):
        scores = clf.decision_function(X)
        exp_scores = np.exp(scores - np.max(scores, axis=1, keepdims=True))
        return exp_scores / exp_scores.sum(axis=1, keepdims=True)
    raise AttributeError("Le classifieur n'expose ni predict_proba ni decision_function.")


def ensure_test_size(actual: int, expected: int | None, strict: bool = False) -> None:
    if expected is None:
        return
    if actual != expected:
        message = (
            f"Jeu de test chargé : {actual} requêtes (attendu {expected}). "
            "Vérifiez le fichier de test avant de poursuivre."
        )
        if strict:
            raise ValueError(message)
        print(f"[AVERTISSEMENT] {message}")


def build_metrics(true_idx: np.ndarray, pred_idx: np.ndarray, proba: np.ndarray) -> Dict[str, float]:
    n_classes = proba.shape[1]
    metrics = {
        "accuracy": float(accuracy_score(true_idx, pred_idx)),
        "precision": float(precision_score(true_idx, pred_idx, average="weighted", zero_division=0)),
        "recall": float(recall_score(true_idx, pred_idx, average="weighted", zero_division=0)),
        "f1_score": float(f1_score(true_idx, pred_idx, average="weighted", zero_division=0)),
        "macro_f1": float(f1_score(true_idx, pred_idx, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(true_idx, pred_idx, average="weighted", zero_division=0)),
        "log_loss": float(log_loss(true_idx, proba, labels=list(range(n_classes)))),
    }
    return metrics


def save_metrics(metrics: Dict[str, float], path: Path) -> None:
    path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")


def save_classification_report(
    report: Dict[str, Any], counts_by_intent: Dict[str, int], correct_by_intent: Dict[str, int], path: Path
) -> None:
    header = [
        "intent",
        "support",
        "correct",
        "incorrect",
        "precision",
        "recall",
        "f1_score",
    ]
    with path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(header)

        for intent, data in sorted(report.items(), key=lambda item: item[0]):
            if intent in {"accuracy", "macro avg", "weighted avg"}:
                continue
            support = int(data.get("support", 0))
            correct = int(correct_by_intent.get(intent, 0))
            incorrect = support - correct
            writer.writerow([
                intent,
                support,
                correct,
                incorrect,
                f"{data.get('precision', 0.0):.4f}",
                f"{data.get('recall', 0.0):.4f}",
                f"{data.get('f1-score', 0.0):.4f}",
            ])

        writer.writerow([])
        for average_label in ["macro avg", "weighted avg"]:
            if average_label in report:
                avg_data = report[average_label]
                writer.writerow([
                    average_label,
                    int(avg_data.get("support", 0)),
                    "",
                    "",
                    f"{avg_data.get('precision', 0.0):.4f}",
                    f"{avg_data.get('recall', 0.0):.4f}",
                    f"{avg_data.get('f1-score', 0.0):.4f}",
                ])
        if "accuracy" in report:
            writer.writerow(["accuracy", int(report["accuracy"] * sum(counts_by_intent.values())), "", "", "", "", ""])


def save_confusion_matrix(cm: np.ndarray, classes: List[str], csv_path: Path, png_path: Path) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["true\\pred"] + classes)
        for intent, row in zip(classes, cm):
            writer.writerow([intent] + [int(value) for value in row])

    if plt is None:
        print("[AVERTISSEMENT] matplotlib n'est pas installé : impossible de générer confusion_matrix.png")
        return

    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(cm, interpolation="nearest", cmap="Blues")
    ax.figure.colorbar(im, ax=ax)
    ax.set(
        xticks=np.arange(len(classes)),
        yticks=np.arange(len(classes)),
        xticklabels=classes,
        yticklabels=classes,
        xlabel="Predicted intent",
        ylabel="True intent",
        title="Matrice de confusion - logreg_calibrated",
    )
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

    thresh = cm.max() / 2.0 if cm.size else 0.0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            color = "white" if cm[i, j] > thresh else "black"
            ax.text(j, i, int(cm[i, j]), ha="center", va="center", color=color, fontsize=8)

    fig.tight_layout()
    fig.savefig(png_path, dpi=200)
    plt.close(fig)


def save_predictions(
    results: List[Dict[str, Any]], path: Path,
) -> None:
    fieldnames = [
        "id",
        "text",
        "true_intent",
        "predicted_intent",
        "confidence",
        "correct",
        "top2_intent",
        "top2_confidence",
    ]
    with path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({
                **row,
                "confidence": f"{row['confidence']:.6f}",
                "top2_confidence": f"{row['top2_confidence']:.6f}",
            })


def save_misclassified(results: List[Dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "id",
        "text",
        "true_intent",
        "predicted_intent",
        "confidence",
        "correct",
        "top2_intent",
        "top2_confidence",
    ]
    with path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            if not row["correct"]:
                writer.writerow({
                    **row,
                    "confidence": f"{row['confidence']:.6f}",
                    "top2_confidence": f"{row['top2_confidence']:.6f}",
                })


def build_confusion_summary(cm: np.ndarray, classes: List[str], limit: int = 20) -> List[Tuple[str, str, int]]:
    pairs: List[Tuple[str, str, int]] = []
    for i, true_intent in enumerate(classes):
        for j, pred_intent in enumerate(classes):
            if i == j:
                continue
            count = int(cm[i, j])
            if count > 0:
                pairs.append((true_intent, pred_intent, count))
    pairs.sort(key=lambda item: item[2], reverse=True)
    return pairs[:limit]


def write_summary_text(
    metrics: Dict[str, float],
    total: int,
    correct: int,
    incorrect: int,
    top_confusions: List[Tuple[str, str, int]],
    path: Path,
    scale_to: int | None = None,
) -> None:
    accuracy_pct = correct / total * 100 if total else 0.0
    error_pct = incorrect / total * 100 if total else 0.0
    lines: List[str] = []
    lines.append("==================================================")
    lines.append("ÉVALUATION DE logreg_calibrated")
    lines.append("==================================================")
    lines.append("")
    lines.append(f"Jeu de test : {total} requêtes")
    if scale_to is not None and scale_to != total:
        factor = scale_to / total if total else 0.0
        lines.append(f"Facteur de mise à l'échelle : {factor:.6f} (vers {scale_to} tests)")
        lines.append("")
        lines.append(f"Equivalent sur {scale_to} tests :")
        lines.append(f"  Correctement classées : {int(round(correct * factor))}")
        lines.append(f"  Mal classées          : {int(round(incorrect * factor))}")
        lines.append("")
    lines.append("")
    lines.append(f"Accuracy          : {metrics['accuracy']:.4f}")
    lines.append(f"Precision (weighted) : {metrics['precision']:.4f}")
    lines.append(f"Recall (weighted)    : {metrics['recall']:.4f}")
    lines.append(f"F1-score (weighted)  : {metrics['f1_score']:.4f}")
    lines.append(f"Macro F1-score       : {metrics['macro_f1']:.4f}")
    lines.append(f"Weighted F1-score    : {metrics['weighted_f1']:.4f}")
    lines.append(f"Log Loss             : {metrics['log_loss']:.4f}")
    lines.append("")
    lines.append(f"Correctement classées : {correct}")
    lines.append(f"Mal classées          : {incorrect}")
    lines.append("")
    lines.append(f"Taux de bonne classification : {accuracy_pct:.4f} %")
    lines.append(f"Taux d'erreur              : {error_pct:.4f} %")
    lines.append("")
    lines.append("==================================================")
    lines.append("TOP 20 DES CONFUSIONS")
    lines.append("==================================================")
    if top_confusions:
        lines.append("Intention réelle -> Intention prédite -> Nombre")
        for true_intent, pred_intent, count in top_confusions:
            lines.append(f"{true_intent} -> {pred_intent} -> {count}")
    else:
        lines.append("Aucune confusion détectée.")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Évalue logreg_calibrated sur le jeu de test NGONI.")
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR, help="Répertoire de sortie des résultats.")
    parser.add_argument(
        "--expected-test-size",
        type=int,
        default=EXPECTED_TEST_SIZE,
        help="Nombre attendu de requêtes dans le jeu de test. Si absent, aucune validation stricte n'est appliquée.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Lever une erreur si le nombre de requêtes diffère de --expected-test-size.",
    )
    parser.add_argument(
        "--scale-to",
        type=int,
        default=DEFAULT_SCALE_TO,
        help="Factoriser les résultats sur ce nombre de tests sans en modifier le calcul réel.",
    )
    args = parser.parse_args()

    results_dir = args.output_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    clf, encoder = load_artifacts()
    pairs = load_test_data()
    ensure_test_size(len(pairs), args.expected_test_size, strict=args.strict)

    texts = [text for text, _ in pairs]
    y_true_labels = [intent for _, intent in pairs]

    unknown_labels = sorted(set(y_true_labels) - set(encoder.classes_))
    if unknown_labels:
        raise ValueError(
            "Le jeu de test contient des intentions inconnues du modèle : "
            f"{unknown_labels}. Vérifiez la configuration du jeu de test."
        )

    n_samples = len(texts)
    if args.scale_to is not None and args.scale_to != n_samples:
        print(
            f"[AVERTISSEMENT] Jeu de test réel : {n_samples} requêtes. "
            f"Résultats projetés sur {args.scale_to} tests via le facteur de mise à l'échelle."
        )
    y_true_idx = encoder.transform(y_true_labels)

    from embed import embed  # noqa: E402

    X = embed(texts)
    proba = predict_proba(clf, X)
    if proba.shape[0] != n_samples:
        raise ValueError(
            f"Nombre de probabilités prédites ({proba.shape[0]}) != nombre de requêtes ({n_samples})."
        )

    y_pred_idx = np.argmax(proba, axis=1)
    predicted_labels = encoder.inverse_transform(y_pred_idx)
    confidences = proba[np.arange(n_samples), y_pred_idx]

    if proba.shape[1] != len(encoder.classes_):
        raise ValueError(
            "Le modèle renvoie un nombre de classes différent de l'encodeur de labels."
        )

    sorted_second = np.argsort(proba, axis=1)
    if proba.shape[1] > 1:
        second_best_idx = sorted_second[:, -2]
    else:
        second_best_idx = sorted_second[:, -1]
    second_best_labels = encoder.inverse_transform(second_best_idx)
    second_best_confidence = proba[np.arange(n_samples), second_best_idx]

    correct_mask = y_true_idx == y_pred_idx
    correct_count = int(np.sum(correct_mask))
    incorrect_count = int(n_samples - correct_count)

    metrics = build_metrics(y_true_idx, y_pred_idx, proba)

    report = classification_report(
        y_true_idx,
        y_pred_idx,
        target_names=list(encoder.classes_),
        labels=list(range(len(encoder.classes_))),
        output_dict=True,
        zero_division=0,
    )

    cm = confusion_matrix(y_true_idx, y_pred_idx, labels=list(range(len(encoder.classes_))))

    counts_by_intent = Counter(y_true_labels)
    correct_by_intent: Dict[str, int] = {}
    for true_label, pred_label in zip(y_true_labels, predicted_labels):
        if true_label == pred_label:
            correct_by_intent[true_label] = correct_by_intent.get(true_label, 0) + 1

    predictions = []
    for idx, (text, true_intent, pred_intent, conf, top2_int, top2_conf, correct) in enumerate(
        zip(texts, y_true_labels, predicted_labels, confidences, second_best_labels, second_best_confidence, correct_mask)
    ):
        predictions.append(
            {
                "id": idx + 1,
                "text": text,
                "true_intent": true_intent,
                "predicted_intent": pred_intent,
                "confidence": float(conf),
                "top2_intent": top2_int,
                "top2_confidence": float(top2_conf),
                "correct": bool(correct),
            }
        )

    save_metrics(metrics, results_dir / "metrics.json")
    save_classification_report(report, counts_by_intent, correct_by_intent, results_dir / "classification_report.csv")
    save_confusion_matrix(cm, list(encoder.classes_), results_dir / "confusion_matrix.csv", results_dir / "confusion_matrix.png")
    save_predictions(predictions, results_dir / "predictions.csv")
    save_misclassified(predictions, results_dir / "misclassified_cases.csv")

    top_confusions = build_confusion_summary(cm, list(encoder.classes_), limit=20)
    write_summary_text(
        metrics,
        n_samples,
        correct_count,
        incorrect_count,
        top_confusions,
        results_dir / "summary.txt",
        scale_to=args.scale_to,
    )

    print("\n==================================================")
    print("ÉVALUATION DE logreg_calibrated")
    print("==================================================")
    print(f"Jeu de test : {n_samples} requêtes")
    if args.scale_to is not None and args.scale_to != n_samples:
        factor = args.scale_to / n_samples if n_samples else 0.0
        print(f"Projection sur {args.scale_to} tests : facteur {factor:.6f}")
    print(f"Accuracy          : {metrics['accuracy']:.4f}")
    print(f"Macro F1-score    : {metrics['macro_f1']:.4f}")
    print(f"Weighted F1-score : {metrics['weighted_f1']:.4f}")
    print(f"Log Loss          : {metrics['log_loss']:.4f}")
    print("")
    print(f"Correctement classées : {correct_count}")
    print(f"Mal classées          : {incorrect_count}")
    print(f"Taux de bonne classification : {correct_count / n_samples * 100:.4f} %")
    print(f"Taux d'erreur              : {incorrect_count / n_samples * 100:.4f} %")
    print("\nFichiers produits dans :", results_dir)
    print("Résumé :", results_dir / "summary.txt")
    print("Matrice de confusion :", results_dir / "confusion_matrix.csv")
    if plt is not None:
        print("Image matrice de confusion :", results_dir / "confusion_matrix.png")
    else:
        print("Image matrice de confusion non générée (matplotlib manquant).")


if __name__ == "__main__":
    main()
