"""Garde-fou de couverture lexicale (voir config.yml, juste avant
FallbackClassifier).

Constate en test live sur /model/parse : DIETClassifier (model_confidence:
softmax) reste extremement sur-confiant (~1.0) meme sur du texte totalement
hors-vocabulaire -- "azefg", "xyz", "zzzz" atterrissaient chacun avec une
confiance de 1.0000 dans une intention existante prise au hasard (dont
"inappropriate_language" : un utilisateur tapant une faute de frappe severe se
faisait accuser de langage inapproprie). Le FallbackClassifier deja en place
(config.yml) est donc inoperant sur ces cas : son seuil ne peut jamais
intercepter une confiance de 1.0000.

Decision actee avec l'utilisateur : ne PAS changer model_confidence (softmax
-> linear_norm, le correctif officiel Rasa pour ce probleme), mais rester sur
softmax et corriger autrement. Ce composant s'insere juste avant
FallbackClassifier dans le pipeline et ne fait qu'UNE chose : si AUCUN mot du
message n'est reconnu dans le vocabulaire complet des donnees d'entrainement
(toutes intentions confondues), il force la confiance de l'intention deja
predite sous le seuil du FallbackClassifier -- qui bascule alors
naturellement sur nlu_fallback, exactement comme s'il avait lui-meme detecte
une confiance insuffisante. Aucune nouvelle action, aucun nouveau slot :
reutilise entierement le mecanisme de fallback deja cable
(core_fallback_action_name -> action_default_fallback, et la regle "Ignore
nlu_fallback/deny/affirm misclassification..." pour le cas ou une question de
diagnostic est en attente, rules.yml).

Ne s'applique qu'aux messages contenant au moins un token alphabetique de 3+
lettres : une reponse structuree ("TOPUP-XYZ-123") ou un simple montant
("1500") n'a par nature aucun mot du langage courant a reconnaitre -- la
garde ne doit pas s'en meler, ces cas sont deja domain par ailleurs (capture
verbatim independante de l'intention, voir rasa/actions/diagnostic.py)."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Text

from rasa.engine.graph import ExecutionContext, GraphComponent
from rasa.engine.recipes.default_recipe import DefaultV1Recipe
from rasa.engine.storage.resource import Resource
from rasa.engine.storage.storage import ModelStorage
from rasa.nlu.classifiers.classifier import IntentClassifier
from rasa.shared.nlu.constants import INTENT, INTENT_NAME_KEY, PREDICTED_CONFIDENCE_KEY, TEXT
from rasa.shared.nlu.training_data.message import Message
from rasa.shared.nlu.training_data.training_data import TrainingData

logger = logging.getLogger(__name__)

WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)
MIN_WORD_LENGTH = 3

# Strictement sous le "threshold" du FallbackClassifier (config.yml) quel que
# soit ce seuil -- on ne duplique pas sa valeur ici, 0.0 est sous n'importe
# quelle valeur raisonnable.
FORCED_CONFIDENCE = 0.0


def _normalize(word: Text) -> Text:
    # Decompose les accents (e -> e + accent aigu combinant) puis retire les
    # marques combinantes : "reçu"/"recu", "problème"/"probleme" matchent
    # ainsi le meme mot du vocabulaire, sans dependance externe (unidecode).
    decomposed = unicodedata.normalize("NFKD", word.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _words(text: Text) -> List[Text]:
    return [_normalize(word) for word in WORD_PATTERN.findall(text) if len(word) >= MIN_WORD_LENGTH]


@DefaultV1Recipe.register(DefaultV1Recipe.ComponentType.INTENT_CLASSIFIER, is_trainable=True)
class VocabularyCoverageGuard(GraphComponent, IntentClassifier):
    """Voir docstring du module."""

    @staticmethod
    def get_default_config() -> Dict[Text, Any]:
        return {}

    def __init__(
        self,
        config: Dict[Text, Any],
        model_storage: ModelStorage,
        resource: Resource,
        execution_context: ExecutionContext,
        vocabulary: Optional[Set[Text]] = None,
    ) -> None:
        self._model_storage = model_storage
        self._resource = resource
        self._execution_context = execution_context
        self.vocabulary = vocabulary or set()

    @classmethod
    def create(
        cls,
        config: Dict[Text, Any],
        model_storage: ModelStorage,
        resource: Resource,
        execution_context: ExecutionContext,
    ) -> "VocabularyCoverageGuard":
        return cls(config, model_storage, resource, execution_context)

    def train(self, training_data: TrainingData) -> Resource:
        vocabulary: Set[Text] = set()
        for example in training_data.training_examples:
            vocabulary.update(_words(example.get(TEXT) or ""))
        self.vocabulary = vocabulary
        logger.info(
            "[DIAG][NLU] VocabularyCoverageGuard entraine avec %d mots distincts",
            len(vocabulary),
        )
        self.persist()
        return self._resource

    def persist(self) -> None:
        with self._model_storage.write_to(self._resource) as model_dir:
            vocab_file = model_dir / f"{self.__class__.__name__}.json"
            vocab_file.write_text(json.dumps(sorted(self.vocabulary)), encoding="utf-8")

    @classmethod
    def load(
        cls,
        config: Dict[Text, Any],
        model_storage: ModelStorage,
        resource: Resource,
        execution_context: ExecutionContext,
        **kwargs: Any,
    ) -> "VocabularyCoverageGuard":
        try:
            with model_storage.read_from(resource) as model_dir:
                vocab_file = model_dir / f"{cls.__name__}.json"
                vocabulary = set(json.loads(vocab_file.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            logger.warning(
                "Impossible de charger VocabularyCoverageGuard depuis le stockage du "
                "modele -- garde desactivee pour cette instance (vocabulaire vide)."
            )
            vocabulary = set()
        return cls(config, model_storage, resource, execution_context, vocabulary)

    def process(self, messages: List[Message]) -> List[Message]:
        for message in messages:
            words = _words(message.get(TEXT) or "")
            if not words:
                continue  # rien a evaluer (reponse structuree, montant, etc.)
            if any(word in self.vocabulary for word in words):
                continue  # au moins un mot reconnu : pas hors-vocabulaire

            intent = message.data.get(INTENT)
            if not intent:
                continue
            original_name = intent.get(INTENT_NAME_KEY)
            original_confidence = intent.get(PREDICTED_CONFIDENCE_KEY)
            intent[PREDICTED_CONFIDENCE_KEY] = FORCED_CONFIDENCE
            logger.info(
                "[DIAG][NLU] stage=vocabulary_guard result=OUT_OF_VOCABULARY text=%r "
                "original_intent=%s original_confidence=%s forced_confidence=%s",
                message.get(TEXT), original_name, original_confidence, FORCED_CONFIDENCE,
            )
        return messages
