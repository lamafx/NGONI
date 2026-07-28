import csv
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple

import requests

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)


def load_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def query_rasa(text: str, rasa_url: str = "http://localhost:5005") -> Dict:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{rasa_url.rstrip('/')}/model/parse",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("intent", {}).get("name", "nlu_fallback")


def compare_rows(rows: List[Dict[str, str]], rasa_url: str) -> List[Dict[str, object]]:
    comparisons: List[Dict[str, object]] = []
    for row in rows:
        text = row.get("text", "")
        true_intent = row.get("true_intent", "")
        knn_pred = row.get("knn_intent", "")
        try:
            rasa_pred = query_rasa(text, rasa_url)
        except Exception:
            rasa_pred = "nlu_unavailable"
        comparisons.append({
            "text": text,
            "true_intent": true_intent,
            "knn_intent": knn_pred,
            "rasa_intent": rasa_pred,
            "knn_correct": knn_pred == true_intent,
            "rasa_correct": rasa_pred == true_intent,
        })
    return comparisons


def main() -> None:
    csv_path = ROOT / "nlu_bge" / "results" / "comparison_full.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV introuvable : {csv_path}")

    rows = load_csv(csv_path)
    comparisons = compare_rows(rows, rasa_url="http://localhost:5005")
    out_path = RESULTS / "knn_vs_rasa_comparison.csv"
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["text", "true_intent", "knn_intent", "rasa_intent", "knn_correct", "rasa_correct"])
        writer.writeheader()
        writer.writerows(comparisons)

    print(f"Comparaison enregistree dans {out_path}")
    knn_correct = sum(1 for row in comparisons if row["knn_correct"])
    rasa_correct = sum(1 for row in comparisons if row["rasa_correct"])
    print(f"KNN accuracy : {knn_correct/len(comparisons):.4f}")
    print(f"Rasa accuracy : {rasa_correct/len(comparisons):.4f}")


if __name__ == "__main__":
    main()
