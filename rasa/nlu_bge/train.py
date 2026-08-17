"""
Entrainement du classifieur d'intention au-dessus des embeddings BGE-M3.

Ce script complete train.py en ajoutant un pipeline dedie a la reduction
du Log Loss :

  1. Rééquilibrage des classes rares via SMOTE, applique directement sur
     les embeddings BGE-M3 (donc sans jamais regenerer de texte synthetique).
  2. Entrainement d'une regression logistique avec recherche du meilleur C
     par validation croisee (grid simple), plutot que le KNN utilise par
     defaut dans train.py.
  3. Calibration des probabilites de sortie (CalibratedClassifierCV) pour
     obtenir des scores de confiance fiables, exploitables pour le seuil
     de fallback vers un agent humain.
  4. Comparaison finale KNN vs LogReg calibree sur les memes folds,
     avec Accuracy / Macro F1 / Log Loss, pour justifier le choix dans
     le memoire.

Pré-requis supplementaire : pip install imbalanced-learn
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, log_loss
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import LabelEncoder

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import intent_counts, load_training_examples  # noqa: E402
from embed import MODEL_NAME, embed  # noqa: E402

MODEL_DIR = Path(__file__).resolve().parent / "model"

# Grille de C testee pour la regression logistique. Une valeur plus faible
# regularise davantage et reduit la surconfiance du modele (donc le Log Loss).
DEFAULT_C_GRID = [0.01, 0.05, 0.1, 0.5, 1.0, 2.0]


def rebalance_rare_classes(X: np.ndarray, y: np.ndarray, min_samples: int = 20, k_neighbors: int = 5):
    """
    Suréchantillonne les classes dont l'effectif est inferieur a min_samples
    en utilisant SMOTE directement sur les embeddings (espace vectoriel
    continu, donc SMOTE y est parfaitement applicable, contrairement a du
    texte brut).

    Les classes deja suffisamment representees ne sont pas touchees.
    """
    from imblearn.over_sampling import SMOTE

    counts = np.bincount(y)
    n_classes = len(counts)

    # Strategie : on ne sur-echantillonne que les classes sous le seuil,
    # on laisse les autres a leur effectif reel.
    sampling_strategy = {
        cls: max(count, min_samples)
        for cls, count in enumerate(counts)
        if count < min_samples
    }

    if not sampling_strategy:
        print("   -> Aucune classe sous le seuil, pas de rééquilibrage necessaire.")
        return X, y

    # k_neighbors de SMOTE doit rester < effectif de la classe la plus petite
    # concernee, sinon SMOTE leve une erreur.
    smallest = min(counts[cls] for cls in sampling_strategy)
    effective_k = max(1, min(k_neighbors, smallest - 1))

    print(f"   -> Classes sous le seuil ({min_samples} ex.) : {len(sampling_strategy)}/{n_classes}")
    print(f"   -> SMOTE avec k_neighbors={effective_k}")

    smote = SMOTE(sampling_strategy=sampling_strategy, k_neighbors=effective_k, random_state=42)
    X_res, y_res = smote.fit_resample(X, y)

    print(f"   -> Taille avant: {len(y)} exemples -> apres: {len(y_res)} exemples")
    return X_res, y_res


def select_best_logreg(X: np.ndarray, y: np.ndarray, c_grid: List[float], cv_folds: int = 5):
    """
    Recherche le meilleur C par validation croisee stratifiee, en optimisant
    le Log Loss (et pas seulement l'accuracy) puisque c'est la metrique
    ciblee ici.
    """
    print(f"Recherche du meilleur C pour la regression logistique parmi : {c_grid}")

    min_class_count = min(np.bincount(y))
    effective_folds = max(2, min(cv_folds, min_class_count))
    skf = StratifiedKFold(n_splits=effective_folds, shuffle=True, random_state=42)

    best_score = np.inf
    best_c = None
    best_clf = None

    for c in c_grid:
        clf = LogisticRegression(max_iter=2000, C=c, class_weight="balanced")
        # cross_val_predict avec method="predict_proba" pour calculer le log loss
        # sur des predictions out-of-fold (pas de fuite de donnees)
        proba = cross_val_predict(clf, X, y, cv=skf, method="predict_proba")
        score = log_loss(y, proba, labels=np.unique(y))
        acc = accuracy_score(y, np.argmax(proba, axis=1))
        print(f"   -> C={c} -> log loss (CV) = {score:.4f} | accuracy (CV) = {acc:.4f}")
        if score < best_score:
            best_score = score
            best_c = c
            best_clf = clf

    print(f"Meilleur C retenu : {best_c} (log loss CV = {best_score:.4f})")
    return best_c, best_score, best_clf


def evaluate_with_calibration(clf, X: np.ndarray, y: np.ndarray, cv_folds: int, method: str = "sigmoid"):
    """
    Enveloppe le classifieur avec CalibratedClassifierCV et evalue par
    validation croisee out-of-fold (donc sans fuite de donnees) :
    Accuracy, Macro F1, Log Loss.
    """
    min_class_count = min(np.bincount(y))
    effective_folds = max(2, min(cv_folds, min_class_count))
    skf = StratifiedKFold(n_splits=effective_folds, shuffle=True, random_state=42)

    calibrated = CalibratedClassifierCV(clf, method=method, cv=skf)
    proba = cross_val_predict(calibrated, X, y, cv=skf, method="predict_proba")
    preds = np.argmax(proba, axis=1)

    metrics = {
        "accuracy": float(accuracy_score(y, preds)),
        "macro_f1": float(f1_score(y, preds, average="macro")),
        "weighted_f1": float(f1_score(y, preds, average="weighted")),
        "log_loss": float(log_loss(y, proba, labels=np.unique(y))),
    }
    return metrics, calibrated


def compare_knn_vs_logreg(X: np.ndarray, y: np.ndarray, cv_folds: int = 5):
    """
    Compare, sur les memes folds, le KNN (baseline actuelle du projet)
    et la regression logistique calibree, pour justifier le changement
    dans le memoire.
    """
    print("\n=== Comparaison KNN (baseline) vs Regression logistique calibree ===")

    min_class_count = min(np.bincount(y))
    effective_folds = max(2, min(cv_folds, min_class_count))
    skf = StratifiedKFold(n_splits=effective_folds, shuffle=True, random_state=42)

    knn = KNeighborsClassifier(n_neighbors=5, weights="distance", metric="cosine")
    proba_knn = cross_val_predict(knn, X, y, cv=skf, method="predict_proba")
    preds_knn = np.argmax(proba_knn, axis=1)
    metrics_knn = {
        "accuracy": float(accuracy_score(y, preds_knn)),
        "macro_f1": float(f1_score(y, preds_knn, average="macro")),
        "weighted_f1": float(f1_score(y, preds_knn, average="weighted")),
        "log_loss": float(log_loss(y, proba_knn, labels=np.unique(y))),
    }

    best_c, _, logreg_clf = select_best_logreg(X, y, DEFAULT_C_GRID, cv_folds=cv_folds)
    metrics_logreg, _ = evaluate_with_calibration(logreg_clf, X, y, cv_folds=cv_folds, method="sigmoid")

    print("\nResultats comparatifs (validation croisee, out-of-fold) :")
    print(f"{'Metrique':<15}{'KNN':>12}{'LogReg calibree':>20}")
    for key in ["accuracy", "macro_f1", "weighted_f1", "log_loss"]:
        print(f"{key:<15}{metrics_knn[key]:>12.4f}{metrics_logreg[key]:>20.4f}")

    return {"knn": metrics_knn, "logreg_calibrated": metrics_logreg, "best_c": best_c}


def persist_model(clf, encoder, classifier_name: str, counts: dict, X: np.ndarray, texts: List[str], extra_meta: dict | None = None) -> None:
    version_dir = MODEL_DIR / "versions" / classifier_name
    version_dir.mkdir(exist_ok=True, parents=True)
    joblib.dump(clf, version_dir / "classifier.joblib")
    joblib.dump(encoder, version_dir / "label_encoder.joblib")
    meta = {
        "embedding_model": MODEL_NAME,
        "classifier": classifier_name,
        "n_examples": len(texts),
        "n_intents": len(counts),
        "intent_counts": counts,
        "embed_dim": int(X.shape[1]),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if extra_meta:
        meta.update(extra_meta)
    (version_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cv-folds", type=int, default=5)
    parser.add_argument("--min-samples", type=int, default=20, help="Effectif minimum par classe avant SMOTE")
    parser.add_argument("--smote-k", type=int, default=5, help="k_neighbors de SMOTE")
    parser.add_argument("--calibration-method", choices=["sigmoid", "isotonic"], default="sigmoid")
    parser.add_argument("--skip-comparison", action="store_true", help="Ne pas comparer avec le KNN baseline")
    args = parser.parse_args()

    pairs = load_training_examples()
    texts = [t for t, _ in pairs]
    labels_raw = [i for _, i in pairs]
    counts = intent_counts(pairs)
    print(f"{len(texts)} exemples, {len(counts)} intentions")

    print("[1/4] Calcul des embeddings d'entrainement (BGE-M3) en cours...")
    t0 = time.perf_counter()
    X = embed(texts)
    print(f"[1/4] Embeddings calcules en {time.perf_counter() - t0:.1f}s, shape={X.shape}")

    encoder = LabelEncoder()
    y = encoder.fit_transform(labels_raw)
    print(f"[2/4] Encodage des labels termine : {len(encoder.classes_)} classes reconnues")

    print("[3/4] Rééquilibrage des classes rares (SMOTE sur les embeddings)...")
    X_res, y_res = rebalance_rare_classes(X, y, min_samples=args.min_samples, k_neighbors=args.smote_k)

    if not args.skip_comparison:
        comparison = compare_knn_vs_logreg(X_res, y_res, cv_folds=args.cv_folds)
    else:
        best_c, _, logreg_template = select_best_logreg(X_res, y_res, DEFAULT_C_GRID, cv_folds=args.cv_folds)
        comparison = {"best_c": best_c}

    print("\n[4/4] Entrainement final de la regression logistique calibree sur l'ensemble rééquilibré...")
    best_c = comparison["best_c"]
    final_clf = LogisticRegression(max_iter=2000, C=best_c, class_weight="balanced")
    final_metrics, calibrated_model = evaluate_with_calibration(
        final_clf, X_res, y_res, cv_folds=args.cv_folds, method=args.calibration_method
    )
    calibrated_model.fit(X_res, y_res)  # fit final sur toutes les donnees rééquilibrées
    print(f"   -> Metriques out-of-fold du modele final : {final_metrics}")

    MODEL_DIR.mkdir(exist_ok=True)
    persist_model(
        calibrated_model,
        encoder,
        "logreg_calibrated",
        counts,
        X_res,
        texts,
        extra_meta={
            "best_c": best_c,
            "min_samples_smote": args.min_samples,
            "smote_k_neighbors": args.smote_k,
            "calibration_method": args.calibration_method,
            "cv_metrics": final_metrics,
            "comparison_vs_knn": comparison.get("knn"),
        },
    )
    joblib.dump(calibrated_model, MODEL_DIR / "classifier.joblib")
    joblib.dump(encoder, MODEL_DIR / "label_encoder.joblib")

    print(f"\nModele final persiste dans {MODEL_DIR}")
    print(f"Log Loss (out-of-fold, avant calibration finale sur le train complet) : {final_metrics['log_loss']:.4f}")


if __name__ == "__main__":
    main()