from __future__ import annotations

import json
import logging
import os
import unicodedata
from typing import Any, Dict, List, Optional, Text

import requests

from rasa.engine.graph import ExecutionContext, GraphComponent
from rasa.engine.recipes.default_recipe import DefaultV1Recipe
from rasa.engine.storage.resource import Resource
from rasa.engine.storage.storage import ModelStorage
from rasa.nlu.classifiers.classifier import IntentClassifier
from rasa.shared.nlu.constants import (
    ENTITIES,
    INTENT,
    INTENT_NAME_KEY,
    INTENT_RANKING_KEY,
    PREDICTED_CONFIDENCE_KEY,
    TEXT,
)
from rasa.shared.nlu.training_data.message import Message
from rasa.shared.nlu.training_data.training_data import TrainingData

logger = logging.getLogger(__name__)

RESOURCE_FILE = " _intent_examples.json"
FALLBACK_INTENT = "nlu_fallback"

# Champs alignes sur domain.yml (`entities:`) ET sur les manifestes de
# diagnostic (voir fastapi/wallet_service/diagnostic/manifest.py, commentaire
# "Noms alignes sur les entites NLU deja entrainees") -- ce chemin existait
# deja cote actions (_capture_opportunistic_nlu_entities, rasa/actions/
# diagnostic.py) mais restait mort faute d'extraction reelle (DIET n'avait
# jamais ete entraine sur ces entites, 0 exemple annote, voir
# docs/18-rapport-competences.md). type_problem/faq_category/faq_slug/
# rating_ref delibrement exclus : les deux derniers viennent des payloads de
# bouton (RegexMessageHandler), pas d'une extraction en langage naturel ;
# type_problem n'a pas de definition claire distincte du probleme classe
# lui-meme.
EXTRACTABLE_ENTITIES = {
    "incident_date": "une date ou expression temporelle liee a l'incident, si le message en contient une",
    "amount": "un montant ou une somme d'argent mentionne, si le message en contient un",
    "platform": "la plateforme mentionnee (iOS, Android, le site web...), si le message en cite une",
    "operation_type": "le type d'operation mentionne (retrait, recharge, cadeau, don...), si le message en cite un",
    "issue_status": "comment le probleme est decrit (bloque, en attente, refuse, annule...), si le message le precise",
}

# Memoire de conversation (metadata.dialogue_context, envoye par le frontend --
# voir buildDialogueContext dans frontend/src/services/chatService.js) : les
# derniers echanges et l'etat de la tache, lus dans le tracker Rasa AVANT
# l'envoi du message. Le composant NLU n'a aucun acces au tracker lui-meme
# (Rasa ne lui transmet que le Message), d'ou ce transport par metadata --
# verifie dans NLUMessageConverter (rasa 3.6.19) : metadata est recopie telle
# quelle dans Message.data.
# DESACTIVE PAR DEFAUT (NLU_CONTEXT_ENABLED=true dans rasa/.env pour
# l'activer, puis redemarrer le conteneur). Mesure A/B sans GPU (2026-10-21,
# meme message "et combien de temps ca prend ?" apres une question FAQ) :
#   sans contexte : 16-17s, question_sur_ngoni (correct)
#   avec contexte : 36-43s, diagnostic + entites inventees (faux)
# Un modele 1.7B tire plus de confusion que d'aide de l'historique, et le
# bloc de contexte, different a chaque message, n'est pas reutilise par le
# cache de Model. Les suites de question FAQ restent gerees sans LLM (voir
# standalone_question, rasa/actions/common.py). A reessayer avec un GPU ou un
# modele plus grand.
CONTEXT_ENABLED = os.getenv("NLU_CONTEXT_ENABLED", "false").strip().lower() in ("1", "true", "yes", "oui")
# 4 entrees = 2 allers-retours : chaque entree coute ~40 tokens de lecture de
# prompt, soit ~0.5s sans GPU (mesure : ~85 tokens/s, voir _build_prompt). Un
# modele 1.7B se perd de toute facon dans un historique plus long.
CONTEXT_MAX_TURNS = int(os.getenv("NLU_CONTEXT_MAX_TURNS", "4"))
CONTEXT_MAX_CHARS = 120

# Le contexte n'est injecte que pour un message ELLIPTIQUE, le seul qui en a
# besoin pour etre compris. Mesure sans GPU (2026-10-21) : le bloc de contexte
# change a chaque message, et la lecture du prompt passait alors de ~4s a
# ~23s -- un cout injustifiable pour "mon retrait de 20000 FCFA est bloque
# depuis hier", qui se comprend parfaitement seul.
CONTEXT_MAX_WORDS = 6
_ELLIPTIC_OPENERS = (
    "et ", "ok", "oui", "non", "alors", "donc", "mais", "pareil", "pour ", "sur ", "avec ",
    "le meme", "la meme", "le même", "la même", "celui", "celle", "ca ", "ça ", "d'accord",
)

# Informations deja donnees, rappelees au modele pour resoudre "le meme",
# "celui d'hier"... Les slots de pilotage (pending_field, requested_slot...)
# n'en font pas partie : ils servent a decider s'il faut injecter le contexte
# (voir _task_is_waiting), pas a l'interpreter.
CONTEXT_FACT_LABELS = {
    "operation_type": "operation",
    "amount": "montant",
    "platform": "plateforme",
    "incident_date": "date de l'incident",
    "issue_status": "etat signale",
    "category": "categorie de reclamation",
}

REFORMULATION_KEY = "standalone_text"

# Definition de chaque intention, inseree dans le prompt AVANT ses exemples.
# Avec 5 exemples seulement, un modele 1.7B classait par ressemblance de
# surface -- mesure (2026-10-21, jeu de phrases absentes de nlu.yml) :
# "Comment recharger mon portefeuille ?" -> request_human_agent,
# "tu supportes quelle equipe de foot ?" -> bot_challenge, toujours a 0.95.
# Cout en latence nul en regime normal : ce texte fait partie du prefixe fixe,
# relu depuis le cache KV de Model (voir _build_prompt). Une intention absente
# d'ici garde simplement ses seuls exemples.
INTENT_DESCRIPTIONS = {
    "affirm": "acquiescement ou reponse positive a la question de l'assistant",
    "deny": "refus ou reponse negative a la question de l'assistant",
    "greet": "salutation seule, avec ou sans formule de politesse (\"ca va ?\"), sans autre demande",
    "goodbye": "l'utilisateur termine la conversation",
    "ask_faq": "question GENERALE sur le fonctionnement de NGONI (comment faire, c'est quoi, combien, "
    "delais, frais, compte, recharge, retrait, KYC, pieces...) sans decrire un incident qu'il subit",
    "diagnostic": "l'utilisateur decrit un PROBLEME CONCRET qu'il subit lui-meme (retrait bloque, "
    "argent non recu, solde faux, application qui plante, compte bloque, verification refusee)",
    "create_reclamation": "demande explicite d'ouvrir une reclamation, un ticket ou de signaler un "
    "probleme, sans encore le decrire",
    "plainte": "mecontentement ou deception sur NGONI en general, sans insulte et sans demande precise",
    "suggestion": "idee ou proposition d'amelioration pour NGONI",
    "ask_complaint_status": "demande ou en est une reclamation ou un ticket deja ouvert",
    "request_human_agent": "demande EXPLICITE de parler a un humain, un conseiller ou un agent -- "
    "une simple demande d'aide n'en est PAS une",
    "cancel_human_agent_request": "annule une demande de conseiller humain faite plus tot",
    "bot_challenge": "demande si l'assistant est un robot, une IA ou un humain, ou qui il est",
    "ask_capabilities": "demande ce que L'ASSISTANT LUI-MEME sait faire ou sur quoi il peut aider -- "
    "une question sur NGONI, ses frais, ses fonctions ou son fonctionnement est ask_faq, pas celle-ci",
    "out_of_scope": "sujet SANS rapport avec NGONI ni avec l'assistant (sport, meteo, cuisine, recettes, "
    "blagues, poemes, politique, maths, geographie, culture generale...)",
    "inappropriate_language": "insulte, grossierete ou propos meprisant envers l'assistant ou le service "
    "(\"t'es nul\", \"idiot\", \"bete\")",
    "rate_response": "donne son avis sur la reponse precedente de l'assistant : la juge utile ou l'en "
    "remercie, ou au contraire dit qu'elle n'aide pas ou ne repond pas -- ce n'est PAS un simple oui ou non",
    "browse_faq": "demande a VOIR ou parcourir les questions frequentes, sans question precise",
    "select_faq": "demande les questions frequentes d'un theme precis (retraits, compte, KYC...)",
}

# Nom sous lequel certaines intentions sont PRESENTEES au modele, retraduit en
# nom Rasa a la sortie (voir _classify) -- le reste du systeme ne voit jamais
# ces alias. Un modele 1.7B se fie beaucoup au nom de l'etiquette : "ask_faq"
# lui est opaque, "ask_capabilities" evoque "est-ce que je peux...". Mesure
# (2026-10-21, deux jeux de phrases absentes de nlu.yml) : la quasi-totalite
# des erreurs restantes etait ask_faq -> ask_capabilities, malgre les
# definitions ci-dessus.
PROMPT_LABELS = {
    "ask_faq": "question_sur_ngoni",
    "ask_capabilities": "competences_de_l_assistant",
    "out_of_scope": "hors_sujet",
    "browse_faq": "parcourir_la_faq",
    "select_faq": "faq_d_un_theme",
}
_LABEL_TO_INTENT = {label: intent for intent, label in PROMPT_LABELS.items()}


def _label(intent: Text) -> Text:
    return PROMPT_LABELS.get(intent, intent)


def _squash(value: Text) -> Text:
    """Minuscules, sans accents ni espaces ni ponctuation : "20 000 FCFA" et
    "20000 fcfa", "bloque" et "bloqué" se comparent egaux."""
    stripped = unicodedata.normalize("NFD", value.lower())
    return "".join(ch for ch in stripped if ch.isalnum())


# Fenetre de contexte demandee a Model, IDENTIQUE pour tous les appels a ce
# modele (voir aussi LLM_REPLY_NUM_CTX, rasa/actions/common.py) : une valeur
# differente d'un appel a l'autre force Model a recharger le modele. Le
# defaut de Model (4096) etait trop juste : prompt fixe ~3300 tokens + bloc
# de contexte ~400 + reponse jusqu'a 250 -- au-dela, Model tronque le DEBUT
# du prompt (consignes et premieres intentions) sans aucune erreur.
MODEL_NUM_CTX = int(os.getenv("MODEL_NUM_CTX", "6144"))


# Questions de SUIVI sur la verification d'identite (« ou en est ma
# verification ? », « mon KYC est valide ? »). Le LLM les classe
# `ask_complaint_status` (« ou en est mon dossier ») -- alors que la reponse
# juste n'est pas un ticket mais le statut KYC reel, que seul le diagnostic
# lit (user_service). Correction ciblee : seulement si la phrase parle
# d'identite/KYC ET ne parle pas de ticket ou de reclamation.
_IDENTITY_TERMS = ("kyc", "verification d identite", "verification de mon identite",
                   "piece d identite", "identite", "compte verifie", "compte est verifie",
                   "ma verification")
_TICKET_TERMS = ("ticket", "reclamation", "plainte", "cmp-")


def _plain(text: Text) -> Text:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.replace("'", " ").replace("’", " ").split())


def _rescue_identity_followup(text: Text, ranking: List[Dict[Text, Any]]) -> List[Dict[Text, Any]]:
    if not ranking or ranking[0].get(INTENT_NAME_KEY) != "ask_complaint_status":
        return ranking
    plain = _plain(text)
    if not any(term in plain for term in _IDENTITY_TERMS) or any(term in plain for term in _TICKET_TERMS):
        return ranking
    logger.info("QwenIntentClassifier : suivi d'identite -> diagnostic (au lieu de ask_complaint_status)")
    confidence = ranking[0].get(PREDICTED_CONFIDENCE_KEY, 0.9)
    rescued = {INTENT_NAME_KEY: "diagnostic", PREDICTED_CONFIDENCE_KEY: confidence}
    # L'intention ecartee est retrogradee nettement : laissee a egalite, le
    # DynamicFallbackClassifier (ecart < ambiguity_threshold) basculait le
    # message en nlu_fallback -- « je n'ai pas bien saisi ».
    demoted = {INTENT_NAME_KEY: "ask_complaint_status", PREDICTED_CONFIDENCE_KEY: round(confidence / 2, 3)}
    others = [r for r in ranking if r.get(INTENT_NAME_KEY) not in ("diagnostic", "ask_complaint_status")]
    return [rescued] + others + [demoted]


@DefaultV1Recipe.register(
    DefaultV1Recipe.ComponentType.INTENT_CLASSIFIER, is_trainable=True
)
class QwenIntentClassifier(GraphComponent, IntentClassifier):
    """Classifieur d'intention ET extracteur d'entites par prompting d'un LLM
    local (le LLM local, servi par Model), en remplacement du le classifieur Rasa historique de ce
    pipeline -- les deux taches dans le MEME appel Model (pas un appel
    separe), pour ne pas doubler la latence deja mesuree comme genante en
    demo (docs/08-pipeline-traitement.md, retours d'usage).

    Contrat de sortie identique a le classifieur Rasa historique/KeywordIntentClassifier cote
    intention : message.data[INTENT] (name/confidence) et
    message.data[INTENT_RANKING_KEY] (liste triee) -- FallbackClassifier
    (seuil + ambiguite) et tout le reste du pipeline fonctionnent sans
    modification, voir rasa/config.yml et docs/07-integration-ia.md du
    depot pour le contrat NLU documente.

    Cote entites (EXTRACTABLE_ENTITIES ci-dessus) : ecrit message.data[ENTITIES]
    au format standard Rasa ([{"entity": "...", "value": "..."}]), consomme
    tel quel par _capture_opportunistic_nlu_entities (rasa/actions/
    diagnostic.py) -- un chemin deja cable mais jusqu'ici toujours vide,
    puisque DIET n'avait jamais ete entraine sur ces entites en pratique.
    """

    @staticmethod
    def get_default_config() -> Dict[Text, Any]:
        return {
            # Rasa tourne dans un conteneur Docker (voir docker-compose.yml) ;
            # Model tourne nativement sur l'hote -- host.docker.internal est
            # l'alias Docker Desktop standard pour joindre l'hote depuis le
            # conteneur (meme principe deja utilise pour actions -> FastAPI,
            # voir README.md principal). "localhost" ici viserait le
            # conteneur lui-meme, pas l'hote.
            "model_url": "http://host.docker.internal:11434/api/chat",
            "model": "qwen3:1.7b",
            "examples_per_intent": 5,
            # 90 et non 30 : sur une machine sans GPU, un message porteur
            # d'entites (montant, date...) a ete mesure a ~24s modele charge,
            # et le tout premier appel apres chargement a ~100s. A 30s, ces
            # messages retombaient sur nlu_fallback en pleine demonstration.
            "request_timeout": 90,
            "keep_alive": "30m",
        }

    def __init__(
        self,
        config: Dict[Text, Any],
        model_storage: ModelStorage,
        resource: Resource,
        execution_context: ExecutionContext,
        intent_examples: Optional[Dict[Text, List[Text]]] = None,
    ) -> None:
        self.component_config = {**self.get_default_config(), **(config or {})}
        self._model_storage = model_storage
        self._resource = resource
        self._execution_context = execution_context
        self.intent_examples: Dict[Text, List[Text]] = intent_examples or {}

    @classmethod
    def create(
        cls,
        config: Dict[Text, Any],
        model_storage: ModelStorage,
        resource: Resource,
        execution_context: ExecutionContext,
    ) -> "QwenIntentClassifier":
        return cls(config, model_storage, resource, execution_context)

    @classmethod
    def load(
        cls,
        config: Dict[Text, Any],
        model_storage: ModelStorage,
        resource: Resource,
        execution_context: ExecutionContext,
        **kwargs: Any,
    ) -> "QwenIntentClassifier":
        intent_examples: Optional[Dict[Text, List[Text]]] = None
        try:
            with model_storage.read_from(resource) as directory:
                content = (directory / RESOURCE_FILE).read_text(encoding="utf-8")
                intent_examples = json.loads(content)
        except ValueError:
            logger.warning(
                "QwenIntentClassifier: ressource entrainee introuvable "
                f"('{resource.name}'), le classifieur repondra nlu_fallback "
                "jusqu'a un nouvel entrainement."
            )
        return cls(config, model_storage, resource, execution_context, intent_examples)

    def train(self, training_data: TrainingData) -> Resource:
        per_intent = self.component_config["examples_per_intent"]
        all_examples: Dict[Text, List[Text]] = {}
        for ex in training_data.intent_examples:
            intent = ex.get(INTENT)
            text = ex.get(TEXT)
            if not intent or not text:
                continue
            bucket = all_examples.setdefault(intent, [])
            if text not in bucket:
                bucket.append(text)
        # Exemples repartis sur TOUTE la liste (milieu de chaque tranche)
        # plutot que les N premiers : nlu.yml regroupe les exemples par vague
        # d'ajout, les premiers d'une intention se ressemblent donc tous
        # (constate : les 5 premiers d'ask_faq parlaient tous de creation de
        # compte, ceux d'out_of_scope etaient des phrases de reponse du bot).
        examples: Dict[Text, List[Text]] = {}
        for intent, texts in all_examples.items():
            if len(texts) <= per_intent:
                examples[intent] = texts
                continue
            step = len(texts) / per_intent
            examples[intent] = [texts[int((i + 0.5) * step)] for i in range(per_intent)]
        self.intent_examples = examples

        with self._model_storage.write_to(self._resource) as directory:
            (directory / RESOURCE_FILE).write_text(
                json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        logger.info(
            "QwenIntentClassifier entraine : %d intentions, %d exemples au total.",
            len(examples),
            sum(len(v) for v in examples.values()),
        )
        return self._resource

    def process(self, messages: List[Message]) -> List[Message]:
        for message in messages:
            text = (message.get(TEXT) or "").strip()

            # Payload structure "/intent{entites}" (boutons, suggestions FAQ
            # cliquables...) : RegexMessageHandler (fin de pipeline, voir
            # rasa/config.yml) fixe deja l'intention exacte (et ses propres
            # entites, issues du payload JSON) a partir de ce texte, et
            # ecrasera de toute facon tout ce qu'on met ici -- lui envoyer un
            # appel LLM serait a la fois inutile (le resultat est jete) et
            # lent (~7-9s perdues sur un clic qui doit etre instantane, voir
            # docs/08-pipeline-traitement.md §8.7).
            if text.startswith("/"):
                message.set(
                    INTENT, {INTENT_NAME_KEY: FALLBACK_INTENT, PREDICTED_CONFIDENCE_KEY: 0.0}, add_to_output=True
                )
                message.set(
                    INTENT_RANKING_KEY,
                    [{INTENT_NAME_KEY: FALLBACK_INTENT, PREDICTED_CONFIDENCE_KEY: 0.0}],
                    add_to_output=True,
                )
                continue

            context_block = self._context_block(message.get("metadata"), text)
            ranking, entities, reformulation = (
                self._classify(text, context_block) if text else ([], [], None)
            )
            if not ranking:
                ranking = [{INTENT_NAME_KEY: FALLBACK_INTENT, PREDICTED_CONFIDENCE_KEY: 0.0}]
            ranking = _rescue_identity_followup(text, ranking)

            message.set(INTENT, ranking[0], add_to_output=True)
            message.set(INTENT_RANKING_KEY, ranking, add_to_output=True)
            message.set(ENTITIES, entities, add_to_output=True)
            # Lu par les actions via tracker.latest_message (voir
            # standalone_question dans rasa/actions/common.py) : "et sur
            # Android ?" ne veut rien dire pour la recherche FAQ, sa
            # reformulation autonome si.
            if reformulation:
                message.set(REFORMULATION_KEY, reformulation, add_to_output=True)
        return messages

    @staticmethod
    def _task_is_waiting(context: Dict[Text, Any]) -> bool:
        """True quand une tache attend une valeur precise : champ de
        reclamation_form (requested_slot) ou precision de diagnostic
        (pending_field). Dans ce cas la machine a etats sait deja ce qu'elle
        attend, et ses regles/mappings sont regles finement sur la
        classification SANS contexte (ex. une reponse classee "plainte" est
        rejetee par le mapping de category, voir reclamation_meta_intents dans
        domain.yml) -- injecter le contexte deplacerait ces classifications.
        """
        slots = context.get("slots") or {}
        if slots.get("pending_field"):
            return True
        return bool(context.get("active_loop") and slots.get("requested_slot"))

    @staticmethod
    def _is_elliptic(text: Text) -> bool:
        lowered = text.strip().lower()
        return len(lowered.split()) <= CONTEXT_MAX_WORDS or lowered.startswith(_ELLIPTIC_OPENERS)

    def _context_block(self, metadata: Any, text: Text = "") -> Text:
        if not CONTEXT_ENABLED or not isinstance(metadata, dict):
            return ""
        if text and not self._is_elliptic(text):
            return ""
        context = metadata.get("dialogue_context")
        if not isinstance(context, dict) or self._task_is_waiting(context):
            return ""

        lines: List[Text] = []
        turns = [t for t in (context.get("turns") or []) if isinstance(t, dict) and t.get("text")]
        for turn in turns[-CONTEXT_MAX_TURNS:]:
            who = "Utilisateur" if turn.get("role") == "user" else "Assistant"
            snippet = " ".join(str(turn["text"]).split())[:CONTEXT_MAX_CHARS]
            lines.append(f'- {who} : "{snippet}"')
        if not lines:
            return ""

        slots = context.get("slots") or {}
        facts = [
            f"{label} = {slots[name]}"
            for name, label in CONTEXT_FACT_LABELS.items()
            if slots.get(name) not in (None, "", False)
        ]

        block = [
            "",
            "Contexte de la conversation -- il sert UNIQUEMENT a interpreter le message, il n'est pas a classer :",
            "Derniers echanges :",
            *lines,
        ]
        if facts:
            block.append("Informations deja donnees par l'utilisateur : " + " ; ".join(facts))
        block += [
            "Utilisation du contexte :",
            "- Reponse courte a la DERNIERE question de l'assistant (\"oui\", \"d'accord\", \"non\", "
            "\"pas maintenant\") : affirm ou deny selon le sens.",
            "- Message qui prolonge le sujet precedent (\"et sur Android ?\", \"et pour un retrait ?\", "
            "\"et si ca ne marche pas ?\") : la meme intention que ce sujet.",
            "- Message qui change clairement de sujet : ignore le contexte.",
            "- Les entites s'extraient UNIQUEMENT du message a classer, jamais du contexte.",
            "- Si le message ne se comprend qu'avec le contexte, ajoute au JSON le champ \"reformulation\" : "
            "la demande reecrite en une phrase autonome et complete (ex. \"et sur Android ?\" apres une "
            "question sur la recharge -> \"Comment recharger mon portefeuille sur Android ?\"). "
            "Sinon, omets ce champ.",
        ]
        return "\n".join(block)

    def _build_prompt(self, text: Text, context_block: Text = "") -> Text:
        # Le message a classer vient en DERNIER : tout ce qui le precede est
        # identique d'un appel a l'autre, et Model reutilise ce prefixe deja
        # calcule (cache KV) au lieu de relire ~1600 tokens a chaque message.
        # Mesure sans GPU (qwen3:1.7b) : lecture du prompt ~19s -> ~3s, memes
        # intentions et memes confiances sur les messages de test.
        lines = [
            "Tu es un classifieur d'intention pour l'assistant de support NGONI, en francais.",
            "Voici la liste EXACTE des intentions valides, chacune avec sa definition et des messages d'exemple deja vus :",
            "",
        ]
        for intent in sorted(self.intent_examples.keys()):
            samples = self.intent_examples[intent]
            examples_str = " / ".join(f'"{s}"' for s in samples)
            description = INTENT_DESCRIPTIONS.get(intent)
            if description:
                lines.append(f"- {_label(intent)} : {description}. Exemples : {examples_str}")
            else:
                lines.append(f"- {_label(intent)} : {examples_str}")
        lines += [
            "",
            "Choisis d'apres la DEFINITION, pas d'apres un mot isole en commun avec un exemple. "
            f"Question sur NGONI ('comment faire', 'c'est quoi', 'est-ce que je peux') -> {_label('ask_faq')} ; "
            f"probleme que l'utilisateur subit -> diagnostic ; sujet etranger a NGONI -> {_label('out_of_scope')}.",
        ]
        lines += [
            "",
            "En plus de l'intention, extrais ces informations -- UNIQUEMENT si elles sont",
            "explicitement presentes dans le message (ne devine JAMAIS une valeur absente) :",
        ]
        for name, description in EXTRACTABLE_ENTITIES.items():
            lines.append(f"- {name} : {description}")
        lines += [
            "",
            # "UNE SEULE ligne" : sans GPU la generation tourne a ~3 tokens/s,
            # et un JSON indente (constate : 15 lignes, 86 tokens, 26s pour un
            # message de diagnostic) coutait plus en espaces qu'en contenu.
            "Reponds UNIQUEMENT avec un objet JSON sur UNE SEULE ligne (aucun retour a la ligne, "
            "aucune indentation), sans aucun texte ni explication autour :",
            '{"ranking": [{"intent": "<une_des_intentions_ci_dessus>", "confidence": <0.0 a 1.0>}], '
            '"entities": {"<nom_du_champ>": "<valeur_telle_qu_ecrite_par_l_utilisateur>"}}',
            "Regles : au plus 2 entrees dans 'ranking', triees par confiance decroissante -- 'confidence' "
            "doit refleter ta reelle incertitude (deux intentions proches = scores proches). Dans "
            "'entities', n'inclus QUE les champs effectivement mentionnes dans le message ; omets "
            "completement les autres (jamais de valeur vide ou nulle). Chaque valeur extraite DOIT "
            "etre un fragment copie MOT POUR MOT du message a classer ci-dessous -- jamais une valeur "
            "inventee, deduite ou reprise d'un exemple. Si rien n'est mentionne, "
            '"entities" doit etre un objet vide {}.',
        ]
        # Le contexte va APRES tout le texte fixe ci-dessus et AVANT le
        # message : le prefixe reste identique d'un appel a l'autre, le cache
        # KV de Model continue donc de servir (voir le commentaire en tete).
        if context_block:
            lines.append(context_block)
        lines += [
            "",
            f'Message a classer : "{text}"',
        ]
        return "\n".join(lines)

    def _classify(
        self, text: Text, context_block: Text = ""
    ) -> tuple[List[Dict[Text, Any]], List[Dict[Text, Any]], Optional[Text]]:
        if not self.intent_examples:
            return [], [], None

        try:
            response = requests.post(
                # MODEL_CHAT_URL prime sur la config figee dans le modele
                # entraine : sous Docker Compose, Model est le service
                # `model`, pas l'hote (voir docker-compose.yml).
                os.getenv("MODEL_CHAT_URL")
                or self.component_config.get("model_url")
                or "http://model:11434/api/chat",
                json={
                    "model": self.component_config["model"],
                    "messages": [{"role": "user", "content": self._build_prompt(text, context_block)}],
                    "stream": False,
                    "format": "json",
                    "think": False,
                    "keep_alive": self.component_config["keep_alive"],
                    "options": {"temperature": 0.0, "num_predict": 250, "num_ctx": MODEL_NUM_CTX},
                },
                timeout=self.component_config["request_timeout"],
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            parsed = json.loads(content)
            raw_ranking = parsed.get("ranking", [])
            raw_entities = parsed.get("entities", {})
            raw_reformulation = parsed.get("reformulation")
        except Exception as exc:  # Model injoignable, timeout, JSON malforme...
            logger.error(
                "QwenIntentClassifier : echec de l'appel a Model (%s) -- "
                "repli sur nlu_fallback pour ce message, aucune entite extraite.",
                exc,
            )
            return [], [], None

        # Reformulation acceptee seulement si un contexte a ete fourni (sans
        # lui, le modele n'a rien sur quoi s'appuyer et ne peut qu'inventer)
        # et si elle reste une phrase raisonnable, differente du message.
        reformulation: Optional[Text] = None
        if context_block and isinstance(raw_reformulation, str):
            candidate = " ".join(raw_reformulation.split())
            if 0 < len(candidate) <= 300 and candidate.lower() != text.strip().lower():
                reformulation = candidate

        known_intents = set(self.intent_examples.keys())
        ranking: List[Dict[Text, Any]] = []
        for item in raw_ranking:
            name = item.get("intent")
            name = _LABEL_TO_INTENT.get(name, name)
            if name not in known_intents:
                continue
            try:
                confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            ranking.append(
                {INTENT_NAME_KEY: name, PREDICTED_CONFIDENCE_KEY: max(0.0, min(1.0, confidence))}
            )
        ranking.sort(key=lambda r: r[PREDICTED_CONFIDENCE_KEY], reverse=True)

        entities: List[Dict[Text, Any]] = []
        if isinstance(raw_entities, dict):
            for name, value in raw_entities.items():
                if name not in EXTRACTABLE_ENTITIES:
                    continue
                if value is None:
                    continue
                value_str = str(value).strip()
                if not value_str:
                    continue
                # Garde-fou deterministe : la consigne "copie mot pour mot"
                # ne suffit pas (constate : "platform": "mobile" extrait de
                # "mon retrait ... est bloque depuis hier"). Une valeur
                # absente du message est une invention, on l'ecarte.
                if _squash(value_str) not in _squash(text):
                    continue
                entities.append({"entity": name, "value": value_str})

        return ranking, entities, reformulation
