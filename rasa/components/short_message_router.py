"""Routage des messages courts/elliptiques vers ask_faq (voir config.yml,
juste apres VocabularyCoverageGuard) -- docs/16-audit-faq-nlu-2026-07.md
16.5 #6 et 16.6 (P2 #12), docs/taches.txt P2 #12.

Constate en conditions reelles (audit du 21 juillet, 16.4) : un message d'un
ou deux mots portant sur un sujet FAQ legitime ("Retrait ?", "KYC",
"Paiement") est presque systematiquement classe `diagnostic` a confiance
proche de 1.0 par DIET -- 25% d'accuracy sur toute la categorie "questions
courtes/ambigues" de cet audit, le pire score mesure. Verifie manuellement
dans cette session (POST /faq/search, une fois l'intention ask_faq
correctement reconnue) que la recherche FAQ hybride (voir
app/domains/faq/service.py, boost mots-cles + suggestions Top-3) gere
CORRECTEMENT ces memes messages courts une fois qu'ils l'atteignent : "KYC"
et "retrait" matchent directement au-dessus du seuil, "modifier" tombe en
"vouliez-vous dire..." avec une suggestion pertinente plutot qu'un echec sec.
Le probleme n'est donc PAS la recherche FAQ elle-meme, mais le routage
d'intention en amont -- ce composant corrige precisement CE maillon.

Portee volontairement etroite (pas un routeur generique "tout message
court") : n'intervient QUE quand l'intention actuellement predite est
`diagnostic`, le seul intent ou cette confusion a ete mesuree. Un message
court deja bien classe (greet: "Aide" 0.962, bot_challenge, affirm/deny...)
n'est jamais touche -- ces intentions restent measurees robustes meme sur
message court ([18. Rapport des competences](../../docs/18-rapport-competences.md)
#5/#6/#7), les reclasser vers ask_faq casserait des flux qui fonctionnent
deja. Ne s'applique pas non plus a un message deja neutralise par
VocabularyCoverageGuard (confidence deja a 0 : mot hors-vocabulaire, ex.
"xyz") -- ce composant doit s'executer APRES lui dans le pipeline pour ne
jamais rerouter du charabia vers une recherche FAQ inutile."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Text

from rasa.engine.graph import ExecutionContext, GraphComponent
from rasa.engine.recipes.default_recipe import DefaultV1Recipe
from rasa.engine.storage.resource import Resource
from rasa.engine.storage.storage import ModelStorage
from rasa.nlu.classifiers.classifier import IntentClassifier
from rasa.shared.nlu.constants import INTENT, INTENT_NAME_KEY, PREDICTED_CONFIDENCE_KEY, TEXT
from rasa.shared.nlu.training_data.message import Message

from .vocabulary_guard import _words

logger = logging.getLogger(__name__)

MAX_WORDS = 2  # "< 3 mots" (docs/taches.txt P2 #12) : 1 ou 2 mots reels.
TARGET_INTENT = "diagnostic"  # seule collision effectivement mesuree (16.4).
REROUTED_INTENT = "ask_faq"
FORCED_CONFIDENCE = 0.95  # au-dessus du threshold FallbackClassifier (config.yml).


@DefaultV1Recipe.register(DefaultV1Recipe.ComponentType.INTENT_CLASSIFIER, is_trainable=False)
class ShortMessageFaqRouter(GraphComponent, IntentClassifier):
    """Voir docstring du module."""

    @staticmethod
    def get_default_config() -> Dict[Text, Any]:
        return {}

    def __init__(self) -> None:
        pass

    @classmethod
    def create(
        cls,
        config: Dict[Text, Any],
        model_storage: ModelStorage,
        resource: Resource,
        execution_context: ExecutionContext,
    ) -> "ShortMessageFaqRouter":
        return cls()

    def process(self, messages: List[Message]) -> List[Message]:
        for message in messages:
            words = _words(message.get(TEXT) or "")
            if not (1 <= len(words) <= MAX_WORDS):
                continue

            intent = message.data.get(INTENT)
            if not intent:
                continue
            original_name = intent.get(INTENT_NAME_KEY)
            original_confidence = intent.get(PREDICTED_CONFIDENCE_KEY)
            if original_name != TARGET_INTENT:
                continue
            if not original_confidence:
                continue  # deja neutralise (VocabularyCoverageGuard) : charabia, pas une vraie question courte.

            intent[INTENT_NAME_KEY] = REROUTED_INTENT
            intent[PREDICTED_CONFIDENCE_KEY] = FORCED_CONFIDENCE
            logger.info(
                "[DIAG][NLU] stage=short_message_router result=REROUTED text=%r "
                "original_intent=%s original_confidence=%s -> intent=%s confidence=%s",
                message.get(TEXT), original_name, original_confidence, REROUTED_INTENT, FORCED_CONFIDENCE,
            )
        return messages
