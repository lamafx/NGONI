import importlib.util
import sys
import types
from pathlib import Path


def load_predict_module():
    module_name = "test_predict_module"
    sys.modules.pop(module_name, None)

    load_calls = []

    def fake_joblib_load(path):
        load_calls.append(path)
        return {"loaded": True}

    fake_joblib = types.ModuleType("joblib")
    fake_joblib.load = fake_joblib_load
    sys.modules["joblib"] = fake_joblib

    fake_dataset = types.ModuleType("dataset")
    fake_dataset.normalize_text = lambda text: text.strip()
    sys.modules["dataset"] = fake_dataset

    fake_embed = types.ModuleType("embed")
    fake_embed.embed_one = lambda text: [1.0, 0.0]
    sys.modules["embed"] = fake_embed

    module_path = Path(__file__).resolve().parents[1] / "nlu_bge" / "predict.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, load_calls


def test_classifier_is_loaded_once_and_reused():
    module, load_calls = load_predict_module()

    first = module._load_artifacts()
    second = module._load_artifacts()

    assert first[0] is second[0]
    assert first[1] is second[1]
    assert len(load_calls) == 2
