"""Entrainement du classifieur d'intention au-dessus des embeddings BGE-M3.

Pipeline : rasa/data/nlu.yml -> embeddings BGE-M3 -> classifieur KNN
avec selection automatique du meilleur k parmi plusieurs valeurs.
Les autres algorithmes sont actuellement desactivés pour ce workflow.
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
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import intent_counts, load_training_examples  # noqa: E402
from embed import MODEL_NAME, embed  # noqa: E402

MODEL_DIR = Path(__file__).resolve().parent / "model"
DEFAULT_KNN_NEIGHBORS = [1, 3, 5, 7, 9]


def build_classifier(name: str, n_neighbors: int | None = None):
    if name == "logreg":
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")
    if name == "svm":
        from sklearn.svm import SVC

        return SVC(kernel="linear", probability=True, class_weight="balanced")
    if name == "mlp":
        from sklearn.neural_network import MLPClassifier

        return MLPClassifier(hidden_layer_sizes=(256,), max_iter=500, early_stopping=True)
    if name == "knn":
        from sklearn.neighbors import KNeighborsClassifier

        return KNeighborsClassifier(n_neighbors=n_neighbors or 5, weights="distance", metric="cosine")
    if name == "rf":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(
            n_estimators=200,
            random_state=42,
            class_weight="balanced",
            n_jobs=-1,
        )
    raise ValueError(f"classifieur inconnu: {name}")


def persist_model(
    clf,
    encoder,
    classifier_name: str,
    counts: dict,
    X: np.ndarray,
    texts: List[str],
    extra_meta: dict | None = None,
) -> None:
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


def select_best_knn_classifier(X: np.ndarray, y: np.ndarray, candidate_neighbors: list[int] | None = None, cv_folds: int = 5):
    candidates = candidate_neighbors or DEFAULT_KNN_NEIGHBORS
    print(f"Recherche du meilleur k pour KNN parmi : {candidates}")

    best_score = -1.0
    best_k = None
    best_clf = None
    best_cv_scores = []

    min_class_count = min(np.bincount(y))
    effective_folds = min(cv_folds, min_class_count)
    if effective_folds < 2:
        print("   -> Validation croisee impossible avec si peu d'exemples par classe, utilisation du premier k.")
        effective_folds = 2

    skf = StratifiedKFold(n_splits=effective_folds, shuffle=True, random_state=42)
    for k in candidates:
        clf = build_classifier("knn", n_neighbors=int(k))
        scores = cross_val_score(clf, X, y, cv=skf, scoring="accuracy")
        mean_score = float(scores.mean())
        print(f"   -> k={k} -> accuracy moyenne = {mean_score:.4f}")
        if mean_score > best_score:
            best_score = mean_score
            best_k = int(k)
            best_clf = clf
            best_cv_scores = [float(v) for v in scores]

    if best_k is None:
        best_k = int(candidates[0])
        best_clf = build_classifier("knn", n_neighbors=best_k)
        best_cv_scores = []

    print(f"Meilleur k retenu : {best_k} (score moyen = {best_score:.4f})")
    return best_k, best_score, best_clf, best_cv_scores


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classifier", choices=["logreg", "svm", "mlp", "knn", "rf"], default="knn")
    parser.add_argument(
        "--classifiers",
        nargs="+",
        choices=["logreg", "svm", "mlp", "knn", "rf"],
        default=["knn"],
        help="Liste des classifieurs a entrainer (par defaut: seul KNN)",
    )
    parser.add_argument("--cv-folds", type=int, default=5)
    parser.add_argument(
        "--knn-neighbors",
        nargs="+",
        type=int,
        default=DEFAULT_KNN_NEIGHBORS,
        help="Valeurs de k a tester pour le KNN",
    )
    args = parser.parse_args()

    pairs = load_training_examples()
    texts = [t for t, _ in pairs]
    labels_raw = [i for _, i in pairs]
    counts = intent_counts(pairs)
    print(f"{len(texts)} exemples, {len(counts)} intentions")

    print("[1/3] Calcul des embeddings d'entrainement (BGE-M3) en cours...")
    t0 = time.perf_counter()
    X = embed(texts)
    embed_seconds = time.perf_counter() - t0
    print(f"[1/3] Embeddings calcules en {embed_seconds:.1f}s, shape={X.shape}")

    encoder = LabelEncoder()
    y = encoder.fit_transform(labels_raw)
    print(f"[2/3] Encodage des labels termine : {len(encoder.classes_)} classes reconnues")

    # Le workflow actuel se limite a KNN afin de comparer Rasa et ce modele.
    # Les autres algorithmes sont conserves en commentaire dans le code pour reference.
    selected_classifiers = ["knn"]
    print(f"[3/3] Debut de l'entrainement pour {len(selected_classifiers)} classifieur(s): {', '.join(selected_classifiers)}")
    for classifier_name in selected_classifiers:
        print(f"\n=== Entrainement {classifier_name} ===")
        if classifier_name == "knn":
            best_k, best_score, best_clf, best_cv_scores = select_best_knn_classifier(
                X,
                y,
                candidate_neighbors=[int(v) for v in args.knn_neighbors],
                cv_folds=args.cv_folds,
            )
            clf = best_clf
            print(f"   -> Entrainement final sur l'ensemble du train set avec k={best_k}...")
            clf.fit(X, y)
            print(f"   -> Entrainement termine pour {classifier_name} (meilleur k={best_k}, score={best_score:.4f})")
        else:
            clf = build_classifier(classifier_name)
            min_class_count = min(counts.values())
            folds = min(args.cv_folds, min_class_count)
            if folds >= 2:
                print(f"   -> Validation croisee en cours ({folds} folds)...")
                skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
                scores = cross_val_score(clf, X, y, cv=skf, scoring="accuracy")
                print(f"   -> Validation croisee terminee : accuracy = {scores.mean():.4f} (+/- {scores.std():.4f})")
            else:
                print(f"   -> Validation croisee ignoree (classe la plus petite a {min_class_count} exemples)")
            print("   -> Entrainement final sur l'ensemble du train set...")
            clf.fit(X, y)
            print(f"   -> Entrainement termine pour {classifier_name}")

        MODEL_DIR.mkdir(exist_ok=True)
        persist_model(
            clf,
            encoder,
            classifier_name,
            counts,
            X,
            texts,
            extra_meta={
                "selected_k": best_k if classifier_name == "knn" else None,
                "candidate_neighbors": [int(v) for v in args.knn_neighbors] if classifier_name == "knn" else None,
                "cv_scores": best_cv_scores if classifier_name == "knn" else None,
                "best_cv_score": best_score if classifier_name == "knn" else None,
            },
        )

        if classifier_name == args.classifier:
            joblib.dump(clf, MODEL_DIR / "classifier.joblib")
            joblib.dump(encoder, MODEL_DIR / "label_encoder.joblib")
            meta = {
                "embedding_model": MODEL_NAME,
                "classifier": classifier_name,
                "n_examples": len(texts),
                "n_intents": len(counts),
                "intent_counts": counts,
                "embed_dim": int(X.shape[1]),
                "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            if classifier_name == "knn":
                meta.update(
                    {
                        "selected_k": best_k,
                        "candidate_neighbors": [int(v) for v in args.knn_neighbors],
                        "cv_scores": best_cv_scores,
                        "best_cv_score": best_score,
                    }
                )
            (MODEL_DIR / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Modeles persistes dans {MODEL_DIR}")


if __name__ == "__main__":
    main()
