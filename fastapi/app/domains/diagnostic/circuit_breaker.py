"""Circuit breaker generique pour les appels du Diagnostic Engine vers les
microservices (Phase 6, etape 25, voir docs/diagnostic-roadmap.md).

Sans disjoncteur, un microservice qui echoue systematiquement (panne
prolongee, pas juste un hoquet reseau) fait quand meme attendre CHAQUE
utilisateur suivant le plein timeout HTTP avant d'escalader -- inutile une
fois la panne averee. Ce disjoncteur fait "echouer vite" (sans appel reseau)
des qu'un service a depasse son seuil d'echecs consecutifs, et retente
periodiquement (etat semi-ouvert) pour detecter automatiquement son retour.

Volontairement independant de httpx/asyncio : aucune dependance externe,
testable en isolation (voir tests/test_diagnostic_circuit_breaker.py).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _BreakerState:
    consecutive_failures: int = 0
    opened_at: float | None = None


class CircuitBreaker:
    """Un disjoncteur PAR CLE (ici : base_url d'un microservice) -- la panne
    d'un service n'affecte jamais l'etat des autres, contrairement a un
    disjoncteur global qui aurait couple leur disponibilite sans raison.

    Etats (implicites, deduits de _BreakerState plutot qu'une enum a
    synchroniser en plus) :
      - FERME  : opened_at est None -> les appels passent normalement.
      - OUVERT : opened_at recent (< reset_timeout_seconds) -> echec immediat,
                 aucun appel reseau tente.
      - SEMI-OUVERT : opened_at ancien (>= reset_timeout_seconds) -> un seul
                 appel est laisse passer pour tester si le service est
                 revenu ; son resultat referme ou reouvre le disjoncteur.
    """

    def __init__(self, failure_threshold: int = 3, reset_timeout_seconds: float = 30.0) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout_seconds = reset_timeout_seconds
        self._states: dict[str, _BreakerState] = {}
        # Verrou volontairement grossier (pas un par cle) : la section
        # critique est de l'ordre de la microseconde (quelques comparaisons
        # d'entiers), pas la peine de complexifier pour un gain de
        # concurrence invisible en pratique sur ce volume d'appels.
        self._lock = threading.Lock()

    def is_open(self, key: str) -> bool:
        with self._lock:
            state = self._states.get(key)
            if state is None or state.opened_at is None:
                return False
            if time.monotonic() - state.opened_at >= self._reset_timeout_seconds:
                # Semi-ouvert : laisse passer CET appel pour tester le
                # service, sans encore le considerer ferme (record_success/
                # record_failure decidera). Ne pas reinitialiser opened_at
                # ici : si cet appel de test echoue aussi, record_failure doit
                # pouvoir rouvrir immediatement sans attendre un nouveau
                # cycle complet de reset_timeout_seconds.
                return False
            return True

    def record_success(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)

    def record_failure(self, key: str) -> None:
        with self._lock:
            state = self._states.setdefault(key, _BreakerState())
            state.consecutive_failures += 1
            if state.consecutive_failures >= self._failure_threshold:
                state.opened_at = time.monotonic()
