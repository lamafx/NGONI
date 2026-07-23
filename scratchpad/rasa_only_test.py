"""Teste Rasa seul (peu importe le modele charge) sur test_cases.csv,
sans passer par le LLM -- sert a comparer le modele de production vs
l'experience CamemBERT-replace chargee via PUT /model."""
import csv
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent


def main():
    with open(HERE / "test_cases.csv", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))

    status = requests.get("http://localhost:5005/status", timeout=10).json()
    model_file = status.get("model_file")
    print(f"Modele charge : {model_file}\n")

    out_path = HERE / f"rasa_only_{model_file.replace('.tar.gz', '')}.csv"
    fieldnames = ["index", "message", "expected_intent", "note", "rasa_intent", "rasa_confidence", "rasa_correct"]
    correct = total = 0

    with open(out_path, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()

        for i, case in enumerate(cases, start=1):
            message = case["message"]
            expected = case["expected_intent"].strip().lower()

            resp = requests.post("http://localhost:5005/model/parse", json={"text": message}, timeout=30)
            data = resp.json()
            intent = data.get("intent", {}).get("name", "NO_PARSE")
            confidence = data.get("intent", {}).get("confidence", 0.0)

            correct_flag = None
            if expected != "incertain":
                total += 1
                correct_flag = intent == expected
                correct += int(correct_flag)

            mark = "OK" if correct_flag else ("SKIP" if correct_flag is None else "FAIL")
            print(f"[{i}/{len(cases)}] attendu={expected:20s} rasa={intent:20s} ({confidence:.3f}) [{mark}]  \"{message[:55]}\"")

            writer.writerow({
                "index": i, "message": message, "expected_intent": expected, "note": case.get("note", ""),
                "rasa_intent": intent, "rasa_confidence": round(confidence, 3), "rasa_correct": correct_flag,
            })

    print(f"\nRESUME ({model_file}) : {correct}/{total} = {100*correct/total:.1f}%")
    print(f"Detail -> {out_path}")


if __name__ == "__main__":
    main()
