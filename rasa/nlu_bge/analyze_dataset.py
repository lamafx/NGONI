"""Audit du dataset NLU (rasa/data/nlu.yml) via similarite cosinus sur les
embeddings BGE-M3 :
  1. quasi-doublons intra-intention (formulations trop artificielles/proches)
  2. paires d'exemples inter-intentions les plus proches (chevauchements de
     frontiere semantique)
Ecrit un rapport avant toute modification du dataset -- cf. plan, Etape 1.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import intent_counts, load_training_examples  # noqa: E402
from embed import embed  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DUP_THRESHOLD = 0.97
CROSS_INTENT_THRESHOLD = 0.90
TOP_CROSS_PAIRS = 60


def main() -> None:
    pairs = load_training_examples()
    texts = [t for t, _ in pairs]
    intents = [i for _, i in pairs]
    print(f"Embedding de {len(texts)} exemples ({len(set(intents))} intentions)...")
    vectors = embed(texts)
    sims = vectors @ vectors.T  # normalise -> produit scalaire = cosinus
    n = len(texts)

    # 1) Quasi-doublons intra-intention
    intra_dup_pairs: List[Tuple[str, str, str, float]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if intents[i] != intents[j]:
                continue
            sim = sims[i, j]
            if sim >= DUP_THRESHOLD:
                intra_dup_pairs.append((intents[i], texts[i], texts[j], float(sim)))

    dup_count_by_intent: Counter = Counter(p[0] for p in intra_dup_pairs)

    # 2) Paires inter-intentions les plus proches (plus proche voisin hors-intention)
    cross_pairs: List[Tuple[str, str, str, str, float]] = []
    for i in range(n):
        row = sims[i].copy()
        row[i] = -1.0
        for j in range(n):
            if intents[j] == intents[i]:
                row[j] = -1.0
        j_best = int(np.argmax(row))
        cross_pairs.append((intents[i], texts[i], intents[j_best], texts[j_best], float(row[j_best])))
    cross_pairs.sort(key=lambda t: -t[4])

    cross_pair_by_intent_couple: Counter = Counter()
    for a, _, b, _, sim in cross_pairs:
        if sim >= CROSS_INTENT_THRESHOLD:
            key = tuple(sorted((a, b)))
            cross_pair_by_intent_couple[key] += 1

    RESULTS_DIR.mkdir(exist_ok=True)
    report_path = RESULTS_DIR / "dataset_audit.md"
    counts = intent_counts(pairs)

    lines: List[str] = []
    lines.append("# Audit du dataset NLU (BGE-M3, similarite cosinus)\n")
    lines.append(f"Genere automatiquement par `analyze_dataset.py` sur "
                  f"`rasa/data/nlu.yml` ({n} exemples, {len(counts)} intentions).\n")

    lines.append("## 1. Repartition par intention\n")
    lines.append("| Intention | Exemples |\n|---|---|")
    for intent, c in counts.items():
        lines.append(f"| {intent} | {c} |")
    lines.append("")

    lines.append(f"## 2. Quasi-doublons intra-intention (cosinus >= {DUP_THRESHOLD})\n")
    lines.append(f"Total : {len(intra_dup_pairs)} paires quasi-identiques.\n")
    lines.append("| Intention | Paires quasi-dupliquees |\n|---|---|")
    for intent, c in dup_count_by_intent.most_common():
        lines.append(f"| {intent} | {c} |")
    lines.append("")
    lines.append("Exemples (5 premiers par intention la plus touchee) :\n")
    shown_per_intent: Counter = Counter()
    for intent, a, b, sim in sorted(intra_dup_pairs, key=lambda t: -t[3]):
        if shown_per_intent[intent] >= 5:
            continue
        shown_per_intent[intent] += 1
        lines.append(f"- **{intent}** ({sim:.3f}) : \"{a}\" / \"{b}\"")
    lines.append("")

    lines.append(f"## 3. Paires inter-intentions les plus proches (cosinus >= {CROSS_INTENT_THRESHOLD})\n")
    lines.append("| Intention A | Intention B | # paires proches |\n|---|---|---|")
    for (a, b), c in cross_pair_by_intent_couple.most_common(20):
        lines.append(f"| {a} | {b} | {c} |")
    lines.append("")
    lines.append(f"Top {TOP_CROSS_PAIRS} paires individuelles les plus proches :\n")
    shown = 0
    seen_intent_pairs: Counter = Counter()
    for a, ta, b, tb, sim in cross_pairs:
        if sim < CROSS_INTENT_THRESHOLD:
            break
        key = tuple(sorted((a, b)))
        if seen_intent_pairs[key] >= 4:
            continue
        seen_intent_pairs[key] += 1
        lines.append(f"- ({sim:.3f}) **{a}**: \"{ta}\" <-> **{b}**: \"{tb}\"")
        shown += 1
        if shown >= TOP_CROSS_PAIRS:
            break

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Rapport ecrit : {report_path}")
    print(f"Quasi-doublons intra-intention : {len(intra_dup_pairs)}")
    print(f"Intentions les plus touchees par les doublons : {dup_count_by_intent.most_common(5)}")
    print(f"Paires inter-intentions les plus frequentes (>= {CROSS_INTENT_THRESHOLD}) : "
          f"{cross_pair_by_intent_couple.most_common(10)}")


if __name__ == "__main__":
    main()
