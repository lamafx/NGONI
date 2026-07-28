"""Exemple de recherche d'hyper-paramètres pour un classifieur sklearn
appliqué sur des features vectorisées issues de Rasa.

Ce script est volontairement autonome et peut servir de base pour un
composant NLU personnalisé ou un benchmark hors ligne.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC


def load_dataset(path: Path) -> Tuple[List[str], List[str]]:
    texts: List[str] = []
    labels: List[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            text, label = line.split("\t", 1)
            texts.append(text)
            labels.append(label)
    return texts, labels


def build_pipeline(model_name: str) -> Pipeline:
    if model_name == "logreg":
        return Pipeline(
            steps=[
                ("tfidf", TfidfVectorizer(ngram_range=(1, 2), analyzer="char_wb")),
                ("clf", LogisticRegression(max_iter=5000, class_weight="balanced", solver="liblinear")),
            ]
        )
    if model_name == "linearsvc":
        return Pipeline(
            steps=[
                ("tfidf", TfidfVectorizer(ngram_range=(1, 2), analyzer="char_wb")),
                ("clf", LinearSVC(class_weight="balanced")),
            ]
        )
    raise ValueError(f"Modele inconnu : {model_name}")


def search_hyperparams(model_name: str, X: List[str], y: List[str], cv: int = 5) -> Dict:
    pipe = build_pipeline(model_name)
    if model_name == "logreg":
        params = {
            "clf__C": [0.1, 0.5, 1.0, 2.0],
            "clf__penalty": ["l2"],
        }
    else:
        params = {
            "clf__C": [0.1, 0.5, 1.0, 2.0],
        }

    search = GridSearchCV(
        pipe,
        params,
        scoring="f1_macro",
        cv=StratifiedKFold(n_splits=cv, shuffle=True, random_state=42),
        n_jobs=-1,
    )
    search.fit(X, y)
    return {
        "best_params": search.best_params_,
        "best_score": float(search.best_score_),
        "best_estimator": search.best_estimator_,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset.tsv")
    parser.add_argument("--model", choices=["logreg", "linearsvc"], default="logreg")
    parser.add_argument("--cv", type=int, default=5)
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {dataset_path}")

    texts, labels = load_dataset(dataset_path)
    result = search_hyperparams(args.model, texts, labels, cv=args.cv)
    print(json.dumps({
        "model": args.model,
        "best_params": result["best_params"],
        "best_score": result["best_score"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
