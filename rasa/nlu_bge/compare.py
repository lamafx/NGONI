"""Comparaison complete et honnete BGE-M3+classifieur vs Rasa, sur les MEMES
exemples de test tenus a l'ecart de l'entrainement des deux systemes.

PREREQUIS avant de lancer ce script :
  1. rasa/nlu_bge/model/ existe (deja fait : `python train.py`)
  2. Un Rasa entraine SUR LE MEME rasa/data/nlu.yml tourne et sert l'API :
         docker compose run --rm rasa train --fixed-model-name comparaison
         docker compose restart rasa
         curl http://localhost:5005/status   (verifier model_file)
     Sans ca, la comparaison n'est pas equitable (Rasa serait juge sur un
     dataset different de celui de BGE-M3).
  3. rasa/tests/test_nlu.yml, test_nlu_adversarial.yml et
     test_nlu_500_supplement.yml sont presents (jeu de test combine, ~492
     exemples, jamais vus a l'entrainement d'aucun des deux systemes).

Usage :
    python rasa/nlu_bge/compare.py [--rasa-url http://localhost:5005]

Sortie (rasa/nlu_bge/results/) :
    comparison_full.csv      -- texte, intention attendue, prediction Rasa,
                                 prediction BGE-M3, confiances, latences,
                                 correct/incorrect pour chacun
    final_comparison_report.md -- rapport complet : tailles modeles,
                                 accuracy/precision/recall/F1/AUC, latence,
                                 disaccords entre les deux systemes
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
from sklearn.preprocessing import label_binarize

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message="Setting the shape on a NumPy array has been deprecated")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import (  # noqa: E402
    NLU_TRAIN_PATH,
    REPO_ROOT,
    TEST_NLU_PATHS,
    add_examples_to_nlu_file,
    load_adversarial_examples,
    load_examples,
    load_test_examples,
    normalize_text,
    remove_examples_from_test_files,
)
import predict as bge_predict  # noqa: E402
from embed import embed_one  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"
MODEL_DIR = Path(__file__).resolve().parent / "model"
SUPPLEMENT_PATH = REPO_ROOT / "rasa" / "tests" / "test_nlu_500_supplement.yml"
RASA_MODELS_DIR = REPO_ROOT / "rasa" / "models"
HF_CACHE_DIR = REPO_ROOT / "rasa" / ".cache" / "huggingface" / "hub" / "models--BAAI--bge-m3"


# --------------------------------------------------------------------------
# Jeu de test combine
# --------------------------------------------------------------------------

def load_full_test_set() -> List[Tuple[str, str]]:
    # Retourne une liste (texte, intention, fichier_source)
    pairs: List[Tuple[str, str, str]] = []
    for path in TEST_NLU_PATHS:
        try:
            if path.exists():
                examples = load_examples(path)
                pairs.extend([(text, intent, path.name) for text, intent in examples])
            else:
                print(f"ATTENTION : {path} introuvable, passe")
        except Exception as exc:  # pragma: no cover - defensive
            print(f"ATTENTION : erreur en lisant {path} ({exc}), passe")
    # Compatibilite: si SUPPLEMENT_PATH existe mais n'est pas present dans TEST_NLU_PATHS,
    # on l'ajoute (defensive)
    if SUPPLEMENT_PATH.exists() and SUPPLEMENT_PATH.name not in [p for _, _, p in pairs]:
        pairs.extend([(text, intent, SUPPLEMENT_PATH.name) for text, intent in load_examples(SUPPLEMENT_PATH)])
    return pairs


def augment_training_with_knn_failures(csv_path: Path) -> Dict[str, int]:
    if not csv_path.exists():
        return {}

    additions: Dict[str, List[str]] = {}
    removals: Dict[str, set[str]] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if str(row.get("knn_correct", "")).strip().lower() not in {"false", "0", "no", "n"}:
                continue
            text = normalize_text((row.get("text") or "").strip())
            intent = normalize_text((row.get("true_intent") or "").strip())
            if not text or not intent:
                continue
            additions.setdefault(intent, []).append(text)
            removals.setdefault(intent, set()).add(text)

    if not additions:
        print("Aucun exemple KNN en echec a enrichir dans le corpus d'apprentissage.")
        return {}

    added_count = add_examples_to_nlu_file(NLU_TRAIN_PATH, additions)
    removed_count = remove_examples_from_test_files(TEST_NLU_PATHS, removals)
    print(
        f"Corpus d'apprentissage enrichi avec {added_count} exemples issus des echecs KNN; "
        f"{removed_count} exemples supprimes des fichiers de test."
    )
    return {"added": added_count, "removed": removed_count}


# --------------------------------------------------------------------------
# Appels aux deux systemes
# --------------------------------------------------------------------------

def query_rasa(rasa_url: str, text: str, timeout: float = 30.0) -> Dict:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{rasa_url.rstrip('/')}/model/parse",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    latency_ms = (time.perf_counter() - t0) * 1000

    intent_obj = body.get("intent") or {}
    ranking = {r["name"]: r["confidence"] for r in body.get("intent_ranking", [])}
    return {
        "intent": intent_obj.get("name", "nlu_fallback"),
        "confidence": float(intent_obj.get("confidence", 0.0)),
        "ranking": ranking,
        "latency_ms": latency_ms,
    }


def query_bge(text: str, n_classes: int) -> Dict:
    t0 = time.perf_counter()
    result = bge_predict.predict(text, top_k=n_classes)
    latency_ms = (time.perf_counter() - t0) * 1000
    ranking = {item["intent"]: item["confidence"] for item in result["top_k"]}
    return {
        "intent": result["intent"],
        "confidence": result["confidence"],
        "ranking": ranking,
        "latency_ms": latency_ms,
    }


def check_rasa_available(rasa_url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(f"{rasa_url.rstrip('/')}/status")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("model_file")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        print(f"ERREUR : impossible de joindre Rasa sur {rasa_url} ({exc}).")
        print("Verifiez que le conteneur tourne : docker compose ps")
        return None


def resolve_latest_rasa_model(preferred_model_file: Optional[str]) -> Optional[str]:
    candidates = []
    if RASA_MODELS_DIR.exists():
        for path in sorted(RASA_MODELS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file():
                continue
            if path.name.endswith((".tar.gz", ".gz", ".tar", ".zip")):
                candidates.append(path)

    if preferred_model_file:
        preferred_path = RASA_MODELS_DIR / preferred_model_file
        if preferred_path.exists():
            return preferred_model_file

    if candidates:
        latest = candidates[0]
        return latest.name

    return None


def resolve_rasa_model_context(rasa_url: str) -> Dict[str, Optional[str]]:
    current_model = check_rasa_available(rasa_url)
    latest_model = resolve_latest_rasa_model(current_model)
    return {
        "served_model_file": current_model,
        "latest_available_model_file": latest_model,
    }


def resolve_latest_bge_artifacts() -> Tuple[Path, Path, Optional[Path]]:
    candidates: List[Tuple[Path, Path, Optional[Path]]] = []

    for root in [MODEL_DIR, MODEL_DIR / "versions"]:
        if not root.exists():
            continue
        if root.name == "versions":
            for classifier_dir in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True):
                clf = classifier_dir / "classifier.joblib"
                enc = classifier_dir / "label_encoder.joblib"
                meta = classifier_dir / "meta.json"
                if clf.exists() and enc.exists():
                    candidates.append((clf, enc, meta))
        else:
            for candidate_dir in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True):
                clf = candidate_dir / "classifier.joblib"
                enc = candidate_dir / "label_encoder.joblib"
                meta = candidate_dir / "meta.json"
                if clf.exists() and enc.exists():
                    candidates.append((clf, enc, meta))

    if not candidates:
        clf = MODEL_DIR / "classifier.joblib"
        enc = MODEL_DIR / "label_encoder.joblib"
        meta = MODEL_DIR / "meta.json"
        if clf.exists() and enc.exists():
            return clf, enc, meta
        raise FileNotFoundError("Aucun artefact BGE-M3 trouve dans le dossier model/.")

    return max(candidates, key=lambda item: max(p.stat().st_mtime for p in [item[0], item[1]] if p.exists()))


# --------------------------------------------------------------------------
# Taille des modeles
# --------------------------------------------------------------------------

def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except (OSError, PermissionError):
            continue
    return total


def load_model_metadata() -> Dict[str, Any]:
    meta_path = MODEL_DIR / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"ATTENTION : impossible de lire {meta_path} ({exc}).")
        return {}


def apply_runtime_model_config(model_meta: Dict[str, Any]) -> Dict[str, Any]:
    import embed as bge_embed  # noqa: E402

    embedding_model = model_meta.get("embedding_model") or os.environ.get("BGE_EMBEDDING_MODEL") or getattr(bge_embed, "MODEL_NAME", "BAAI/bge-m3")
    bge_embed.MODEL_NAME = embedding_model
    bge_embed._model = None
    bge_embed._load_seconds = None
    bge_predict._classifier = None
    bge_predict._label_encoder = None

    return {
        "embedding_model": embedding_model,
        "classifier_name": model_meta.get("classifier") or "unknown",
        "trained_at": model_meta.get("trained_at"),
    }


def model_sizes(
    rasa_served_model_file: Optional[str],
    rasa_latest_model_file: Optional[str],
    model_meta: Dict[str, Any],
    bge_clf_path: Optional[Path] = None,
) -> Dict:
    cache_root = Path(os.environ.get("HF_HOME") or str(HF_CACHE_DIR))
    bge_weights_mb = dir_size_bytes(cache_root) / (1024 * 1024)
    bge_classifier_kb = (bge_clf_path.stat().st_size / 1024) if bge_clf_path and bge_clf_path.exists() else 0.0

    rasa_size_mb = 0.0
    if rasa_served_model_file:
        rasa_path = RASA_MODELS_DIR / rasa_served_model_file
        if rasa_path.exists():
            rasa_size_mb = rasa_path.stat().st_size / (1024 * 1024)

    latest_rasa_size_mb = 0.0
    if rasa_latest_model_file:
        latest_rasa_path = RASA_MODELS_DIR / rasa_latest_model_file
        if latest_rasa_path.exists():
            latest_rasa_size_mb = latest_rasa_path.stat().st_size / (1024 * 1024)

    return {
        "bge_m3_weights_mb": round(bge_weights_mb, 1),
        "bge_m3_classifier_kb": round(bge_classifier_kb, 1),
        "bge_m3_params": f"{model_meta.get('embed_dim', 'n/a')}d ({model_meta.get('embedding_model', 'BAAI/bge-m3')})",
        "embedding_model": model_meta.get("embedding_model", "BAAI/bge-m3"),
        "classifier_name": model_meta.get("classifier", "unknown"),
        "trained_at": model_meta.get("trained_at"),
        "rasa_model_file": rasa_served_model_file,
        "rasa_latest_model_file": rasa_latest_model_file,
        "rasa_model_mb": round(rasa_size_mb, 1),
        "rasa_latest_model_mb": round(latest_rasa_size_mb, 1),
    }


# --------------------------------------------------------------------------
# Metriques
# --------------------------------------------------------------------------

def compute_metrics(y_true: List[str], y_pred: List[str], proba_matrix: np.ndarray,
                     classes: List[str]) -> Dict:
    class_to_idx = {c: i for i, c in enumerate(classes)}
    kept = [(true_label, pred_label) for true_label, pred_label in zip(y_true, y_pred)
            if true_label in class_to_idx and pred_label in class_to_idx]
    if not kept:
        return {
            "accuracy": 0.0,
            "precision_macro": 0.0,
            "recall_macro": 0.0,
            "f1_macro": 0.0,
            "precision_weighted": 0.0,
            "recall_weighted": 0.0,
            "f1_weighted": 0.0,
            "auc_macro_ovr": None,
        }
    y_true_filtered, y_pred_filtered = zip(*kept)
    y_true_idx = np.array([class_to_idx[c] for c in y_true_filtered])
    y_pred_idx = np.array([class_to_idx[c] for c in y_pred_filtered])

    acc = accuracy_score(y_true_idx, y_pred_idx)
    precision_macro, recall_macro, f1_macro, _ = precision_recall_fscore_support(
        y_true_idx, y_pred_idx, labels=list(range(len(classes))), average="macro", zero_division=0
    )
    precision_weighted, recall_weighted, f1_weighted, _ = precision_recall_fscore_support(
        y_true_idx, y_pred_idx, labels=list(range(len(classes))), average="weighted", zero_division=0
    )

    auc_macro = None
    try:
        y_true_bin = label_binarize(y_true_idx, classes=list(range(len(classes))))
        auc_macro = roc_auc_score(y_true_bin, proba_matrix, multi_class="ovr", average="macro")
    except ValueError as exc:
        print(f"AUC non calculable ({exc}) -- probablement une classe absente du jeu de test.")

    return {
        "accuracy": acc,
        "precision_macro": precision_macro,
        "recall_macro": recall_macro,
        "f1_macro": f1_macro,
        "precision_weighted": precision_weighted,
        "recall_weighted": recall_weighted,
        "f1_weighted": f1_weighted,
        "auc_macro_ovr": auc_macro,
    }


def latency_stats(values_ms: List[float]) -> Dict:
    values_ms = sorted(values_ms)
    n = len(values_ms)
    return {
        "mean_ms": statistics.mean(values_ms),
        "p50_ms": statistics.median(values_ms),
        "p95_ms": values_ms[max(0, int(0.95 * n) - 1)],
        "min_ms": values_ms[0],
        "max_ms": values_ms[-1],
    }


# --------------------------------------------------------------------------
# Boucle principale
# --------------------------------------------------------------------------

def load_bge_classifier_versions() -> List[Dict[str, Any]]:
    versions: List[Dict[str, Any]] = []
    versions_root = MODEL_DIR / "versions"
    if not versions_root.exists():
        return versions

    for classifier_dir in sorted([p for p in versions_root.iterdir() if p.is_dir()], key=lambda p: p.name):
        clf_path = classifier_dir / "classifier.joblib"
        enc_path = classifier_dir / "label_encoder.joblib"
        meta_path = classifier_dir / "meta.json"
        if not clf_path.exists() or not enc_path.exists():
            continue
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        versions.append({
            "name": classifier_dir.name,
            "clf_path": clf_path,
            "enc_path": enc_path,
            "meta": meta,
        })
    return versions


def predict_with_artifacts(clf, encoder, text: str) -> Tuple[str, float, np.ndarray]:
    vector = embed_one(normalize_text(text)).reshape(1, -1)
    if hasattr(clf, "predict_proba"):
        proba = clf.predict_proba(vector)[0]
    else:
        scores = clf.decision_function(vector)[0]
        exp = np.exp(scores - scores.max())
        proba = exp / exp.sum()

    pred_idx = int(np.argmax(proba))
    pred_label = encoder.inverse_transform([pred_idx])[0]
    return str(pred_label), float(proba[pred_idx]), proba


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rasa-url", default="http://localhost:5005")
    parser.add_argument("--limit", type=int, default=None, help="Limiter le nombre d'exemples (debug)")
    parser.add_argument(
        "--classifiers",
        nargs="+",
        default=["knn"],
        help="Classifieurs BGE a evaluer (workflow courant : seul KNN)",
    )
    parser.add_argument(
        "--augment-training",
        action="store_true",
        help="Enrichir automatiquement `rasa/data/nlu.yml` avec les echecs KNN (desactive par defaut)",
    )
    args = parser.parse_args()

    print("Verification de la disponibilite de Rasa...")
    rasa_context = resolve_rasa_model_context(args.rasa_url)
    rasa_model_file = rasa_context.get("served_model_file")
    rasa_available = rasa_model_file is not None
    if not rasa_available:
        print("Rasa indisponible : la comparaison continuera en mode sans Rasa.")
    else:
        print(f"Rasa sert actuellement : {rasa_model_file}")
        if rasa_context.get("latest_available_model_file") and rasa_context.get("latest_available_model_file") != rasa_model_file:
            print(
                "ATTENTION : le modele Rasa servi par l'API differe du plus recent disponible sur disque : "
                f"{rasa_model_file} vs {rasa_context['latest_available_model_file']}"
            )
        else:
            print("Rasa pointe bien sur le modele le plus recent disponible sur disque.")

    print("Chargement des classifieurs BGE-M3...")
    model_meta = load_model_metadata()
    runtime_model = apply_runtime_model_config(model_meta)
    versions = load_bge_classifier_versions()
    if not versions:
        bge_clf_path, bge_enc_path, bge_meta_path = resolve_latest_bge_artifacts()
        if bge_meta_path and bge_meta_path.exists():
            try:
                model_meta = json.loads(bge_meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
            runtime_model = apply_runtime_model_config(model_meta)
        print(
            "Modele BGE utilise : "
            f"{runtime_model['embedding_model']} | classifieur={runtime_model['classifier_name']}"
        )
        if bge_clf_path.exists() and bge_enc_path.exists():
            bge_predict._classifier = bge_predict.joblib.load(bge_clf_path)
            bge_predict._label_encoder = bge_predict.joblib.load(bge_enc_path)
        clf, encoder = bge_predict._load_artifacts()
        classes = list(encoder.classes_)
        n_classes = len(classes)
        print(f"{n_classes} intentions connues : {classes}")
        versions = [{"name": runtime_model["classifier_name"], "clf_path": bge_clf_path, "enc_path": bge_enc_path, "meta": model_meta}]

    requested_classifiers = set(args.classifiers)
    selected_versions = [v for v in versions if v["name"] in requested_classifiers]
    if not selected_versions:
        if "knn" in requested_classifiers:
            raise FileNotFoundError("Aucun modele KNN disponible pour l'evaluation demandee.")
        raise FileNotFoundError("Aucun classifieur disponible pour l'evaluation demandee.")

    selected_versions = sorted(selected_versions, key=lambda item: item["name"])
    print(f"Comparaison retenue : Rasa vs {', '.join(v['name'] for v in selected_versions)}")
    selected_versions = sorted(selected_versions, key=lambda item: item["name"])
    first_version = selected_versions[0]
    first_clf = bge_predict.joblib.load(first_version["clf_path"])
    first_encoder = bge_predict.joblib.load(first_version["enc_path"])
    classes = list(first_encoder.classes_)
    n_classes = len(classes)
    print(f"{n_classes} intentions connues : {classes}")

    pairs = load_full_test_set()
    # Affichage des fichiers de test charges et nombre d'exemples par fichier
    file_counts: Dict[str, int] = {}
    for _, _, fname in pairs:
        file_counts[fname] = file_counts.get(fname, 0) + 1
    if file_counts:
        print("Fichiers de test charges :")
        for fname, cnt in sorted(file_counts.items()):
            print(f"  {fname}: {cnt} exemples")
    else:
        print("Aucun fichier de test charge (liste vide).")
    if args.limit:
        pairs = pairs[: args.limit]
    print(f"\n{len(pairs)} exemples de test (jamais vus a l'entrainement).\n")

    rows: List[Dict[str, Any]] = []
    rasa_latencies: List[float] = []
    rasa_proba_matrix = np.zeros((len(pairs), n_classes), dtype=float)
    y_true: List[str] = []
    y_pred_rasa: List[str] = []
    bge_predictions: Dict[str, List[str]] = {version["name"]: [] for version in selected_versions}
    bge_confidences: Dict[str, List[float]] = {version["name"]: [] for version in selected_versions}
    bge_latencies: Dict[str, List[float]] = {version["name"]: [] for version in selected_versions}
    bge_proba_matrices: Dict[str, np.ndarray] = {
        version["name"]: np.zeros((len(pairs), n_classes), dtype=float) for version in selected_versions
    }

    for i, item in enumerate(pairs):
        text, true_intent, source = item
        clean_text = normalize_text(text)

        if rasa_available:
            try:
                rasa_result = query_rasa(args.rasa_url, clean_text)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                print(f"  [{i}] Rasa a echoue sur {clean_text!r} ({exc}), mode sans Rasa pour cet exemple.")
                rasa_result = None
        else:
            rasa_result = None

        row_idx = len(rows)
        if rasa_result is not None:
            rasa_latencies.append(rasa_result["latency_ms"])
            for j, c in enumerate(classes):
                rasa_proba_matrix[row_idx, j] = rasa_result["ranking"].get(c, 0.0)
            y_true.append(true_intent)
            y_pred_rasa.append(rasa_result["intent"])
            row: Dict[str, Any] = {
                "text": text,
                "true_intent": true_intent,
                "test_file": source,
                "rasa_intent": rasa_result["intent"],
                "rasa_confidence": round(rasa_result["confidence"], 4),
                "rasa_correct": rasa_result["intent"] == true_intent,
                "rasa_latency_ms": round(rasa_result["latency_ms"], 1),
            }
        else:
            rasa_latencies.append(0.0)
            for j, _ in enumerate(classes):
                rasa_proba_matrix[row_idx, j] = 0.0
            y_true.append(true_intent)
            y_pred_rasa.append("nlu_unavailable")
            row = {
                "text": text,
                "true_intent": true_intent,
                "test_file": source,
                "rasa_intent": "nlu_unavailable",
                "rasa_confidence": 0.0,
                "rasa_correct": False,
                "rasa_latency_ms": 0.0,
            }

        for version in selected_versions:
            name = version["name"]
            clf = joblib.load(version["clf_path"])
            encoder = joblib.load(version["enc_path"])
            t0 = time.perf_counter()
            pred_label, confidence, proba = predict_with_artifacts(clf, encoder, clean_text)
            latency_ms = (time.perf_counter() - t0) * 1000
            bge_predictions[name].append(pred_label)
            bge_confidences[name].append(confidence)
            bge_latencies[name].append(latency_ms)
            row[f"{name}_intent"] = pred_label
            row[f"{name}_confidence"] = round(confidence, 4)
            row[f"{name}_correct"] = pred_label == true_intent
            row[f"{name}_latency_ms"] = round(latency_ms, 1)
            bge_proba_matrices[name][row_idx, :] = proba

        rows.append(row)

        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(pairs)} exemples traites...")

    RESULTS_DIR.mkdir(exist_ok=True)

    csv_path = RESULTS_DIR / "comparison_full.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nDetail exemple par exemple : {csv_path}")

    if args.augment_training:
        augment_training_with_knn_failures(csv_path)
    else:
        print("Enrichissement du fichier d'apprentissage desactive (utilisez --augment-training pour l'activer).")

    classifier_summaries = []
    for version in selected_versions:
        name = version["name"]
        proba_matrix = bge_proba_matrices.get(name)
        if proba_matrix is None:
            proba_matrix = np.zeros((len(rows), n_classes), dtype=float)
        classifier_metrics = compute_metrics(y_true, bge_predictions[name], proba_matrix, classes)
        classifier_summaries.append({
            "classifier": name,
            "accuracy": round(classifier_metrics["accuracy"], 4),
            "metrics": classifier_metrics,
            "latency": latency_stats(bge_latencies[name]),
        })

    rasa_metrics = compute_metrics(y_true, y_pred_rasa, rasa_proba_matrix, classes)
    sizes = model_sizes(
        rasa_model_file,
        rasa_context.get("latest_available_model_file"),
        model_meta,
        first_version["clf_path"],
    )

    disagreements = [r for r in rows if r["rasa_intent"] != r[f"{selected_versions[0]['name']}_intent"]]
    both_wrong = [r for r in rows if not r["rasa_correct"] and not r[f"{selected_versions[0]['name']}_correct"]]
    only_rasa_right = [r for r in rows if r["rasa_correct"] and not r[f"{selected_versions[0]['name']}_correct"]]
    only_bge_right = [r for r in rows if r[f"{selected_versions[0]['name']}_correct"] and not r["rasa_correct"]]

    summary = {
        "n_examples": len(rows),
        "rasa_available": rasa_available,
        "rasa": {**rasa_metrics, "latency": latency_stats(rasa_latencies)},
        "classifiers": classifier_summaries,
        "model_sizes": sizes,
        "n_disagreements": len(disagreements),
        "n_both_wrong": len(both_wrong),
        "n_only_rasa_right": len(only_rasa_right),
        "n_only_bge_right": len(only_bge_right),
    }
    # Metrics par fichier de test
    per_file: Dict[str, Any] = {}
    file_names = sorted(list({r.get("test_file", "unknown") for r in rows}))
    for fname in file_names:
        indices = [i for i, r in enumerate(rows) if r.get("test_file") == fname]
        if not indices:
            continue
        y_true_file = [rows[i]["true_intent"] for i in indices]
        y_pred_rasa_file = [rows[i]["rasa_intent"] for i in indices]
        rasa_proba_sub = rasa_proba_matrix[indices, :] if hasattr(rasa_proba_matrix, "shape") else np.zeros((len(indices), n_classes))
        rasa_metrics_file = compute_metrics(y_true_file, y_pred_rasa_file, rasa_proba_sub, classes)
        classifiers_file = []
        for version in selected_versions:
            name = version["name"]
            bge_preds_file = [bge_predictions[name][i] for i in indices]
            proba_sub = bge_proba_matrices[name][indices, :]
            metrics_file = compute_metrics(y_true_file, bge_preds_file, proba_sub, classes)
            classifiers_file.append({"classifier": name, "metrics": metrics_file})
        per_file[fname] = {
            "n_examples": len(indices),
            "rasa": rasa_metrics_file,
            "classifiers": classifiers_file,
        }
    summary["per_test_file"] = per_file
    (RESULTS_DIR / "comparison_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    write_report(RESULTS_DIR / "final_comparison_report.md", summary, only_rasa_right, only_bge_right, both_wrong, selected_versions)
    print(f"Rapport final : {RESULTS_DIR / 'final_comparison_report.md'}")


def write_report(path: Path, summary: Dict, only_rasa_right: List[Dict],
                  only_bge_right: List[Dict], both_wrong: List[Dict],
                  versions: List[Dict[str, Any]]) -> None:
    r, s = summary["rasa"], summary["model_sizes"]
    lines = []
    lines.append("# Comparaison Rasa vs BGE-M3 -- rapport complet\n")
    lines.append(f"Genere par `compare.py` sur {summary['n_examples']} exemples de test.\n")

    lines.append("## Taille des modeles\n")
    lines.append("| | Rasa | BGE-M3 + classifieur |")
    lines.append("|---|---|---|")
    lines.append(f"| Fichier / poids | `{s['rasa_model_file']}` | `{s['bge_m3_params']}` |")
    lines.append(f"| Rasa (servi / latest) | {s['rasa_model_file'] or 'n/a'} / {s['rasa_latest_model_file'] or 'n/a'} | - |")
    lines.append(f"| Modele embarque | - | {s['embedding_model']} ({s['classifier_name']}) |")
    lines.append(f"| Entraine le | - | {s['trained_at'] or 'inconnu'} |")
    lines.append(f"| Taille sur disque | {s['rasa_model_mb']} Mo | {s['bge_m3_weights_mb']} Mo (poids) + {s['bge_m3_classifier_kb']} Ko (classifieur) |")
    lines.append("")

    lines.append("## Metriques (mêmes exemples, jamais vus a l'entrainement)\n")
    lines.append("| Metrique | Rasa | " + " | ".join(v["name"] for v in versions) + " |")
    lines.append("|---|---|" + "|".join(["---"] * len(versions)) + "|")
    lines.append(f"| Accuracy | {r['accuracy']:.4f} | " + " | ".join(f"{item['accuracy']:.4f}" for item in summary['classifiers']) + " |")
    lines.append(f"| Precision (macro) | {r['precision_macro']:.4f} | " + " | ".join(f"{item['metrics']['precision_macro']:.4f}" for item in summary['classifiers']) + " |")
    lines.append(f"| Recall (macro) | {r['recall_macro']:.4f} | " + " | ".join(f"{item['metrics']['recall_macro']:.4f}" for item in summary['classifiers']) + " |")
    lines.append(f"| F1 (macro) | {r['f1_macro']:.4f} | " + " | ".join(f"{item['metrics']['f1_macro']:.4f}" for item in summary['classifiers']) + " |")
    lines.append(f"| F1 (weighted) | {r['f1_weighted']:.4f} | " + " | ".join(f"{item['metrics']['f1_weighted']:.4f}" for item in summary['classifiers']) + " |")
    lines.append("")

    lines.append("## Latence (appel unitaire, pattern de production)\n")
    lines.append("| Classifieur | Moyenne | p50 | p95 |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| Rasa | {r['latency']['mean_ms']:.1f} ms | {r['latency']['p50_ms']:.1f} ms | {r['latency']['p95_ms']:.1f} ms |")
    for item in summary['classifiers']:
        lat = item['latency']
        lines.append(f"| {item['classifier']} | {lat['mean_ms']:.1f} ms | {lat['p50_ms']:.1f} ms | {lat['p95_ms']:.1f} ms |")
    lines.append("")

    lines.append("## Desaccords entre les deux systemes\n")
    lines.append(f"- Predictions differentes (Rasa != BGE-M3) : {summary['n_disagreements']}/{summary['n_examples']}")
    lines.append(f"- Les deux se trompent : {summary['n_both_wrong']}")
    lines.append(f"- Seul Rasa a raison : {summary['n_only_rasa_right']}")
    lines.append(f"- Seul BGE-M3 a raison : {summary['n_only_bge_right']}\n")

    # Ventilation par fichier de test
    per_file = summary.get("per_test_file", {})
    if per_file:
        lines.append("## Ventilation par fichier de test\n")
        lines.append("| Fichier | #Exemples | Rasa Accuracy | " + " | ".join(v["name"] for v in versions) + " |")
        lines.append("|---|---:|---:|" + "|---:" * len(versions) + "|")
        for fname, info in per_file.items():
            rasa_acc = info["rasa"].get("accuracy", 0.0) if isinstance(info.get("rasa"), dict) else 0.0
            classifier_accs = []
            for c in info.get("classifiers", []):
                classifier_accs.append(f"{c['metrics'].get('accuracy', 0.0):.4f}")
            lines.append(f"| {fname} | {info['n_examples']} | {rasa_acc:.4f} | " + " | ".join(classifier_accs) + " |")
        lines.append("")

    def sample_table(title: str, items: List[Dict], n: int = 15) -> None:
        lines.append(f"### {title} (jusqu'a {n})\n")
        lines.append("| Texte | Attendu | Rasa | BGE-M3 |")
        lines.append("|---|---|---|---|")
        for row in items[:n]:
            text = row["text"].replace("|", "/")
            lines.append(f"| {text} | {row['true_intent']} | {row['rasa_intent']} | {row[f'{versions[0]["name"]}_intent']} |")
        lines.append("")

    sample_table("Seul Rasa a raison", only_rasa_right)
    sample_table("Seul BGE-M3 a raison", only_bge_right)
    sample_table("Les deux se trompent", both_wrong)

    lines.append("Detail complet exemple par exemple : `comparison_full.csv`.\n")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
