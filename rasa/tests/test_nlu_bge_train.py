import importlib.util
import sys
from pathlib import Path

import numpy as np


def load_train_module():
    module_name = "nlu_bge_train"
    sys.modules.pop(module_name, None)

    module_path = Path(__file__).resolve().parents[1] / "nlu_bge" / "train.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_build_classifier_supports_random_forest():
    module = load_train_module()

    clf = module.build_classifier("rf")

    assert clf.__class__.__name__ == "RandomForestClassifier"


def test_select_best_knn_classifier_returns_best_k():
    module = load_train_module()

    X = np.array([
        [0.0, 0.0],
        [0.0, 0.1],
        [1.0, 0.0],
        [1.0, 0.1],
        [0.2, 0.0],
        [0.1, 0.1],
        [0.8, 0.0],
        [0.9, 0.1],
    ])
    y = np.array([0, 0, 1, 1, 0, 0, 1, 1])

    best_k, best_score = module.select_best_knn_classifier(X, y, candidate_neighbors=[1, 3], cv_folds=2)

    assert best_k in {1, 3}
    assert 0.0 <= best_score <= 1.0
