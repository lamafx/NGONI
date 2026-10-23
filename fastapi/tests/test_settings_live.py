"""Seuils relus a chaud par le moteur (LIVE_PARAMETERS) : la route publique
GET /settings/engine que lit le conteneur Rasa, le cache de live.py, et leur
effet sur le repli manuel des moteurs bge_sklearn. Sans base ni Rasa : le
repository est remplace par un double en memoire.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_db  # noqa: E402
from app.domains.nlu import engines  # noqa: E402
from app.domains.settings import live  # noqa: E402
from app.domains.settings.router import engine_router  # noqa: E402
from app.domains.settings.service import SystemParameterService  # noqa: E402


class FakeRepository:
    def __init__(self, values):
        self.values = values

    def list_all(self):
        return [SimpleNamespace(param_id=k, value=v) for k, v in sorted(self.values.items())]


@pytest.fixture(autouse=True)
def clear_live_cache():
    live.invalidate()
    yield
    live.invalidate()


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(engine_router)
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_engine_route_exposes_only_live_overrides(monkeypatch):
    repo = FakeRepository({"nlu.confidence_threshold": 0.75, "faq.default_threshold": 0.6})
    monkeypatch.setattr(SystemParameterService, "from_session", classmethod(lambda cls, s: cls(repo)))

    response = make_client().get("/settings/engine")

    assert response.status_code == 200
    assert response.json() == {"nlu.confidence_threshold": 0.75}


def test_engine_route_is_empty_when_nothing_overridden(monkeypatch):
    repo = FakeRepository({})
    monkeypatch.setattr(SystemParameterService, "from_session", classmethod(lambda cls, s: cls(repo)))

    assert make_client().get("/settings/engine").json() == {}


def _patch_session(monkeypatch, repo_or_error):
    import app.database as database

    class FakeSession:
        def close(self):
            pass

    def from_session(cls, session):
        if isinstance(repo_or_error, Exception):
            raise repo_or_error
        return cls(repo_or_error)

    monkeypatch.setattr(database, "SessionLocal", FakeSession)
    monkeypatch.setattr(SystemParameterService, "from_session", classmethod(from_session))


def test_live_value_reads_override_then_default(monkeypatch):
    _patch_session(monkeypatch, FakeRepository({"nlu.confidence_threshold": 0.75}))

    assert live.live_value("nlu.confidence_threshold", 0.70) == 0.75
    assert live.live_value("nlu.ambiguity_threshold", 0.10) == 0.10


def test_invalidate_makes_a_new_value_visible_immediately(monkeypatch):
    repo = FakeRepository({"nlu.confidence_threshold": 0.70})
    _patch_session(monkeypatch, repo)
    assert live.live_value("nlu.confidence_threshold", 0.70) == 0.70

    repo.values["nlu.confidence_threshold"] = 0.80
    assert live.live_value("nlu.confidence_threshold", 0.70) == 0.70  # encore en cache
    live.invalidate()
    assert live.live_value("nlu.confidence_threshold", 0.70) == 0.80


def test_database_outage_keeps_last_known_value(monkeypatch):
    _patch_session(monkeypatch, FakeRepository({"nlu.confidence_threshold": 0.80}))
    assert live.live_value("nlu.confidence_threshold", 0.70) == 0.80

    _patch_session(monkeypatch, OperationalError("SELECT", {}, Exception("down")))
    monkeypatch.setattr(live, "REFRESH_SECONDS", 0.0)
    assert live.live_value("nlu.confidence_threshold", 0.70) == 0.80


class FakeClassifier:
    def __init__(self, proba):
        self.proba = np.array([proba])

    def predict_proba(self, vector):
        return self.proba


class FakeEncoder:
    def inverse_transform(self, idx):
        return [["diagnostic", "plainte"][idx[0]]]


class FakeEmbeddingModel:
    def encode(self, text, **kwargs):
        return np.zeros(4)


@pytest.mark.parametrize(
    ("override", "expected_intent"),
    [({}, "diagnostic"), ({"nlu.confidence_threshold": 0.80}, "nlu_fallback")],
)
def test_bge_fallback_follows_admin_threshold(monkeypatch, override, expected_intent):
    """0.75 de confiance : compris au seuil par defaut (0.70), renvoye vers le
    repli des que l'admin resserre le seuil a 0.80."""
    _patch_session(monkeypatch, FakeRepository(override))
    monkeypatch.setattr(engines, "_load_bge_classifier", lambda name: (FakeClassifier([0.75, 0.25]), FakeEncoder()))
    monkeypatch.setattr(engines, "get_embedding_model", lambda: FakeEmbeddingModel())

    prediction = engines._predict_bge_sync("logreg", "ma vérification est bloquée")

    assert prediction.intent == expected_intent
    assert prediction.confidence == pytest.approx(0.75)
