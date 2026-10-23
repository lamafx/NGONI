"""FallbackClassifier dont les seuils se relisent a chaud depuis l'espace Admin.

Le FallbackClassifier de Rasa fige `threshold` et `ambiguity_threshold` dans
le modele entraine : changer rasa/config.yml impose de reentrainer puis de
redemarrer le conteneur. Ce composant garde exactement son comportement
(verifie sur rasa 3.6.19, rasa/nlu/classifiers/fallback_classifier.py : toute
la decision lit self.component_config) et se contente de mettre a jour ces
deux cles avant chaque lot de messages, a partir de GET /settings/engine
(fastapi/app/domains/settings/router.py, engine_router).

Les valeurs de config.yml restent les valeurs PAR DEFAUT : une surcharge
retiree cote admin les retablit. Si FastAPI ne repond pas, la derniere valeur
connue est conservee -- un seuil resserre ne doit pas se relacher en silence
pendant une coupure (meme regle que fastapi/app/domains/settings/live.py).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Text

import requests

from rasa.engine.recipes.default_recipe import DefaultV1Recipe
from rasa.nlu.classifiers.fallback_classifier import (
    AMBIGUITY_THRESHOLD_KEY,
    THRESHOLD_KEY,
    FallbackClassifier,
)
from rasa.shared.nlu.training_data.message import Message

logger = logging.getLogger(__name__)

# host.docker.internal : ce composant tourne dans le conteneur Rasa, FastAPI
# nativement sur l'hote -- meme convention que les URLs de rasa/actions/.env.
ENGINE_SETTINGS_URL = os.getenv("ENGINE_SETTINGS_URL", "http://host.docker.internal:8000/settings/engine")
# Une requete au plus toutes les REFRESH_SECONDS, pas une par message : le
# classifieur LLM qui precede coute deja plusieurs secondes par tour, ce
# composant ne doit rien y ajouter de perceptible.
REFRESH_SECONDS = float(os.getenv("ENGINE_SETTINGS_REFRESH_SECONDS", "5"))
REQUEST_TIMEOUT_SECONDS = 0.5

# Identifiants cote admin (fastapi/app/domains/settings/service.py,
# LIVE_PARAMETERS) -> cles de configuration du FallbackClassifier.
PARAM_TO_CONFIG_KEY = {
    "nlu.confidence_threshold": THRESHOLD_KEY,
    "nlu.ambiguity_threshold": AMBIGUITY_THRESHOLD_KEY,
}


@DefaultV1Recipe.register(DefaultV1Recipe.ComponentType.INTENT_CLASSIFIER, is_trainable=False)
class DynamicFallbackClassifier(FallbackClassifier):
    def __init__(self, config: Dict[Text, Any]) -> None:
        # Copie : la config recue est celle du schema du graphe, partagee --
        # la muter a chaque rafraichissement n'est pas l'affaire de ce composant.
        super().__init__(dict(config))
        self._defaults = {key: self.component_config[key] for key in PARAM_TO_CONFIG_KEY.values()}
        self._fetched_at: Optional[float] = None

    def process(self, messages: List[Message]) -> List[Message]:
        self._refresh_thresholds()
        return super().process(messages)

    def _refresh_thresholds(self) -> None:
        now = time.monotonic()
        if self._fetched_at is not None and now - self._fetched_at < REFRESH_SECONDS:
            return
        self._fetched_at = now

        try:
            response = requests.get(ENGINE_SETTINGS_URL, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            overrides = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Seuils du moteur illisibles (%s) : derniere valeur conservee.", exc)
            return
        if not isinstance(overrides, dict):
            logger.warning("Seuils du moteur : reponse inattendue %r, ignoree.", overrides)
            return

        for param_id, key in PARAM_TO_CONFIG_KEY.items():
            value = overrides.get(param_id)
            target = float(value) if isinstance(value, (int, float)) else self._defaults[key]
            if target != self.component_config[key]:
                logger.info("Seuil %s : %.2f -> %.2f (espace Admin)", key, self.component_config[key], target)
                self.component_config[key] = target
