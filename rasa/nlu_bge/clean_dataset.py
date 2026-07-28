"""Nettoyage chirurgical de rasa/data/nlu.yml a partir des resultats de
analyze_dataset.py :
  1. corrige les 2 contradictions d'etiquetage exactes (meme texte, deux
     intentions differentes, cosinus 1.000)
  2. deduplique les quasi-doublons intra-intention (cosinus >= 0.97) : garde
     la premiere occurrence de chaque groupe, retire les suivantes
  3. reduit la redondance combinatoire residuelle de `suggestion` et
     `plainte` (gabarits x idees croisés) par selection gloutonne
     maximisant la diversite, jusqu'a une taille cible

Edite UNIQUEMENT les lignes d'exemples concernees (texte brut, sans
annotation d'entite) -- prealablement invariant : conserve tous les
commentaires et la structure du fichier. Mode dry-run par defaut (n'ecrit
rien, affiche/enregistre la liste des suppressions proposees) ; --apply pour
reecrire rasa/data/nlu.yml.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import NLU_TRAIN_PATH, load_training_examples, strip_entity_annotations  # noqa: E402
from embed import embed  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DUP_THRESHOLD = 0.97

# Les 2 contradictions exactes trouvees par l'audit (cosinus 1.000, texte
# identique, intentions differentes) : (texte, intention_a_retirer).
EXACT_CONTRADICTIONS: List[Tuple[str, str]] = [
    ("Quelles sont les fonctionnalités disponibles ?", "ask_faq"),
    ("nickel", "rate_response_useful"),
]

# Intentions a reduire par diversite gloutonne au-dela du simple dedup, et
# taille cible (voir rapport d'audit : blocs gabarites combinatoires).
DIVERSITY_TARGETS: Dict[str, int] = {
    "suggestion": 90,
    "plainte": 90,
}


def union_find_clusters(n: int, pairs: List[Tuple[int, int]]) -> Dict[int, List[int]]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in pairs:
        union(a, b)

    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)
    return clusters


def greedy_diverse_subset(indices: List[int], vectors: np.ndarray, target: int) -> List[int]:
    """Selection gloutonne max-min : part d'un exemple, ajoute a chaque etape
    celui dont la similarite MAX avec le sous-ensemble deja choisi est la
    plus FAIBLE (donc le plus different de ce qui est deja garde)."""
    if len(indices) <= target:
        return indices
    sub_vectors = vectors[indices]
    n = len(indices)
    chosen = [0]
    sims_to_chosen = sub_vectors @ sub_vectors[0]
    while len(chosen) < target:
        sims_to_chosen_masked = sims_to_chosen.copy()
        sims_to_chosen_masked[chosen] = 2.0  # exclu deja choisi
        next_idx = int(np.argmin(sims_to_chosen_masked))
        chosen.append(next_idx)
        new_sims = sub_vectors @ sub_vectors[next_idx]
        sims_to_chosen = np.maximum(sims_to_chosen, new_sims)
    return [indices[i] for i in chosen]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Ecrit reellement rasa/data/nlu.yml (sinon dry-run)")
    args = parser.parse_args()

    pairs = load_training_examples()
    texts = [t for t, _ in pairs]
    intents = [i for _, i in pairs]
    print(f"Embedding de {len(texts)} exemples pour le nettoyage...")
    vectors = embed(texts)
    n = len(texts)

    to_remove: Set[Tuple[str, str]] = set()  # (intent, text)

    # 1) Contradictions exactes
    for text, intent_to_drop in EXACT_CONTRADICTIONS:
        to_remove.add((intent_to_drop, text))

    # 2) Quasi-doublons intra-intention -> clusters, garde le 1er, retire le reste
    by_intent_indices: Dict[str, List[int]] = {}
    for idx, intent in enumerate(intents):
        by_intent_indices.setdefault(intent, []).append(idx)

    dup_removed = 0
    for intent, idxs in by_intent_indices.items():
        idxs_arr = np.array(idxs)
        sub = vectors[idxs_arr]
        sim = sub @ sub.T
        local_pairs = []
        m = len(idxs)
        for i in range(m):
            for j in range(i + 1, m):
                if sim[i, j] >= DUP_THRESHOLD:
                    local_pairs.append((i, j))
        clusters = union_find_clusters(m, local_pairs)
        for root, members in clusters.items():
            if len(members) <= 1:
                continue
            members_sorted = sorted(members)  # garde le premier (ordre d'apparition dans le fichier)
            for local_idx in members_sorted[1:]:
                global_idx = idxs_arr[local_idx]
                key = (intent, texts[global_idx])
                if key not in to_remove:
                    to_remove.add(key)
                    dup_removed += 1

    print(f"Quasi-doublons retires (cosinus >= {DUP_THRESHOLD}) : {dup_removed}")

    # 3) Diversite gloutonne pour suggestion/plainte au-dela du dedup strict
    for intent, target in DIVERSITY_TARGETS.items():
        remaining = [idx for idx in by_intent_indices.get(intent, [])
                     if (intent, texts[idx]) not in to_remove]
        if len(remaining) <= target:
            print(f"{intent}: {len(remaining)} exemples apres dedup, deja <= cible {target}, rien de plus a retirer")
            continue
        kept = set(greedy_diverse_subset(remaining, vectors, target))
        dropped_here = 0
        for idx in remaining:
            if idx not in kept:
                to_remove.add((intent, texts[idx]))
                dropped_here += 1
        print(f"{intent}: {len(remaining)} -> {target} par selection gloutonne diverse "
              f"({dropped_here} retires en plus)")

    print(f"\nTotal a retirer : {len(to_remove)} exemples")

    RESULTS_DIR.mkdir(exist_ok=True)
    removals_path = RESULTS_DIR / "removals.csv"
    with removals_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["intent", "text"])
        for intent, text in sorted(to_remove):
            writer.writerow([intent, text])
    print(f"Liste des suppressions ecrite dans {removals_path}")

    remaining_counts: Dict[str, int] = {}
    for intent in intents:
        remaining_counts[intent] = remaining_counts.get(intent, 0) + 1
    for intent, text in to_remove:
        remaining_counts[intent] -= 1
    print("\nComptages apres nettoyage (projection) :")
    for intent, c in sorted(remaining_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {intent}: {c}")

    if not args.apply:
        print("\nDry-run : rien ecrit dans nlu.yml. Relancer avec --apply pour appliquer.")
        return

    apply_removals(to_remove)


def apply_removals(to_remove: Set[Tuple[str, str]]) -> None:
    lines = NLU_TRAIN_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    current_intent: str | None = None
    output_lines: List[str] = []
    removed_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- intent:"):
            current_intent = stripped.split(":", 1)[1].strip()
            output_lines.append(line)
            continue
        if current_intent is not None and stripped.startswith("- ") and not stripped.startswith("- intent:"):
            raw = stripped[2:].strip()
            text = strip_entity_annotations(raw)
            if (current_intent, text) in to_remove:
                removed_count += 1
                continue
        output_lines.append(line)

    NLU_TRAIN_PATH.write_text("".join(output_lines), encoding="utf-8")
    print(f"\n{removed_count} lignes supprimees, rasa/data/nlu.yml reecrit.")


if __name__ == "__main__":
    main()
