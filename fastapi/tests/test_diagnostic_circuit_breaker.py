"""Tests du disjoncteur (Phase 6, etape 25, voir docs/diagnostic-roadmap.md).
Purement logique, aucune dependance HTTP/DB -- voir
test_diagnostic_adapter_resilience.py pour la preuve que l'Adapter s'arrete
bien d'appeler le reseau une fois le disjoncteur ouvert."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.diagnostic.circuit_breaker import CircuitBreaker  # noqa: E402


def test_closed_by_default():
    breaker = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=30.0)
    assert breaker.is_open("service-a") is False


def test_stays_closed_below_failure_threshold():
    breaker = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=30.0)
    breaker.record_failure("service-a")
    breaker.record_failure("service-a")
    assert breaker.is_open("service-a") is False


def test_opens_at_failure_threshold():
    breaker = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=30.0)
    breaker.record_failure("service-a")
    breaker.record_failure("service-a")
    breaker.record_failure("service-a")
    assert breaker.is_open("service-a") is True


def test_success_resets_failure_count():
    breaker = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=30.0)
    breaker.record_failure("service-a")
    breaker.record_failure("service-a")
    breaker.record_success("service-a")
    breaker.record_failure("service-a")
    breaker.record_failure("service-a")
    # Seulement 2 echecs consecutifs depuis le succes -- pas encore ouvert.
    assert breaker.is_open("service-a") is False


def test_each_service_key_is_independent():
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=30.0)
    breaker.record_failure("service-a")
    breaker.record_failure("service-a")
    assert breaker.is_open("service-a") is True
    assert breaker.is_open("service-b") is False


def test_half_open_after_reset_timeout_allows_a_trial_call():
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.05)
    breaker.record_failure("service-a")
    assert breaker.is_open("service-a") is True

    time.sleep(0.06)

    # Semi-ouvert : le prochain appel est laisse passer (is_open == False)
    # pour tester si le service est revenu.
    assert breaker.is_open("service-a") is False


def test_half_open_trial_failure_reopens_immediately():
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.05)
    breaker.record_failure("service-a")
    time.sleep(0.06)
    assert breaker.is_open("service-a") is False  # semi-ouvert, essai autorise

    breaker.record_failure("service-a")  # l'essai a echoue

    assert breaker.is_open("service-a") is True  # rouvert sans attendre un nouveau cycle complet


def test_half_open_trial_success_closes_the_breaker():
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.05)
    breaker.record_failure("service-a")
    time.sleep(0.06)
    assert breaker.is_open("service-a") is False

    breaker.record_success("service-a")

    assert breaker.is_open("service-a") is False
