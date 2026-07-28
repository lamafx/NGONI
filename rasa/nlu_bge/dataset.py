"""Lecture des fichiers NLU au format Rasa (rasa/data/nlu.yml,
rasa/tests/test_nlu*.yml) sans dependre du package `rasa` (non installe hors
du conteneur dedie) -- seul le format YAML + bloc litteral `examples: |` est
necessaire ici.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Set, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
NLU_TRAIN_PATH = REPO_ROOT / "rasa" / "data" / "nlu.yml"
TEST_NLU_PATH = REPO_ROOT / "rasa" / "tests" / "test_nlu.yml"
TEST_NLU_ADVERSARIAL_PATH = REPO_ROOT / "rasa" / "tests" / "test_nlu_adversarial.yml"
TEST_NLU_SUPPLEMENT_PATH = REPO_ROOT / "rasa" / "tests" / "test_nlu_500_supplement.yml"
TEST_NLU_PATHS = [TEST_NLU_PATH, TEST_NLU_ADVERSARIAL_PATH, TEST_NLU_SUPPLEMENT_PATH]

_ENTITY_ANNOTATION = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def strip_entity_annotations(text: str) -> str:
    """"[texte](entity:valeur)" -> "texte" -- les spans d'entites ne sont pas
    pertinents pour un classifieur d'intention au niveau phrase."""
    return _ENTITY_ANNOTATION.sub(r"\1", text).strip()


def normalize_text(text: str) -> str:
    """Pretraitement minimal : espaces normalises, forme Unicode NFC.
    BGE-M3 gere nativement la casse/les accents, pas besoin de plus."""
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_examples_block(block: str) -> List[str]:
    examples: List[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not stripped.startswith("- "):
            continue
        raw = stripped[2:].strip()
        text = strip_entity_annotations(raw)
        text = normalize_text(text)
        if text:
            examples.append(text)
    return examples


def load_examples(path: Path) -> List[Tuple[str, str]]:
    """Retourne une liste (texte, intention). Une meme intention peut
    apparaitre dans plusieurs blocs `- intent: X` du fichier (convention
    documentee dans test_nlu_adversarial.yml) -- les blocs sont fusionnes."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_intent: Dict[str, List[str]] = {}
    for block in data.get("nlu", []):
        intent = block.get("intent")
        examples_raw = block.get("examples")
        if not intent or not examples_raw:
            continue
        by_intent.setdefault(intent, []).extend(_parse_examples_block(examples_raw))

    pairs: List[Tuple[str, str]] = []
    for intent, examples in by_intent.items():
        for text in examples:
            pairs.append((text, intent))
    return pairs


def load_training_examples() -> List[Tuple[str, str]]:
    return load_examples(NLU_TRAIN_PATH)


def load_test_examples() -> List[Tuple[str, str]]:
    return load_examples(TEST_NLU_PATH)


def load_adversarial_examples() -> List[Tuple[str, str]]:
    return load_examples(TEST_NLU_ADVERSARIAL_PATH)


def _build_examples_block(examples: List[str]) -> str:
    if not examples:
        return "|\n"
    return "|\n" + "\n".join(f"    - {example}" for example in examples)


def add_examples_to_nlu_file(path: Path, additions: Dict[str, List[str]]) -> int:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    nlu_blocks = data.get("nlu", [])
    added = 0
    for block in nlu_blocks:
        intent = block.get("intent")
        if not intent:
            continue
        if intent not in additions:
            continue
        existing_examples = _parse_examples_block(block.get("examples", ""))
        existing_set = set(existing_examples)
        for example in additions[intent]:
            normalized = normalize_text(example)
            if not normalized or normalized in existing_set:
                continue
            existing_examples.append(normalized)
            existing_set.add(normalized)
            added += 1
        block["examples"] = _build_examples_block(existing_examples)
    if added:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return added


def remove_examples_from_test_files(paths: List[Path], removals: Dict[str, Set[str]]) -> int:
    removed = 0
    for path in paths:
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        nlu_blocks = data.get("nlu", [])
        updated_blocks = []
        for block in nlu_blocks:
            intent = block.get("intent")
            if not intent:
                updated_blocks.append(block)
                continue
            examples = _parse_examples_block(block.get("examples", ""))
            keep_examples = [example for example in examples if example not in removals.get(intent, set())]
            if keep_examples:
                block["examples"] = _build_examples_block(keep_examples)
                updated_blocks.append(block)
                removed += len(examples) - len(keep_examples)
            else:
                removed += len(examples)
        data["nlu"] = updated_blocks
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return removed


def intent_counts(pairs: List[Tuple[str, str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for _, intent in pairs:
        counts[intent] = counts.get(intent, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


if __name__ == "__main__":
    train = load_training_examples()
    test = load_test_examples()
    adversarial = load_adversarial_examples()
    print(f"train: {len(train)} exemples, {len(intent_counts(train))} intentions")
    for intent, n in intent_counts(train).items():
        print(f"  {intent}: {n}")
    print(f"test_nlu.yml: {len(test)} exemples")
    print(f"test_nlu_adversarial.yml: {len(adversarial)} exemples")
