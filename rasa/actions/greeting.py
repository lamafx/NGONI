import random
from datetime import datetime
from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

from .capabilities import AGENT_CAPABILITIES, _join_naturally
from .faq import fetch_faq_category_buttons

# Variantes de formulation (accueil / invitation / cloture) : tirees au sort a
# chaque accueil pour que le message ne semble jamais fige d'une conversation
# a l'autre, sans jamais toucher au contenu factuel (salutation selon l'heure,
# capacites reelles de l'agent) -- seul l'habillage varie.
_WELCOME_VARIANTS = [
    "Bienvenue chez NGONI.",
    "Ravi de vous accueillir sur NGONI.",
    "Merci de nous rejoindre sur NGONI.",
]

_INVITATION_VARIANTS = [
    "N'hésitez pas à me poser votre question.",
    "Comment puis-je vous aider aujourd'hui ?",
    "Dites-moi ce qui vous amène, je suis à votre écoute.",
]

_CLOSING_VARIANTS = [
    "Vous pouvez aussi choisir une catégorie ci-dessous pour découvrir des exemples de questions.",
    "Vous pouvez également vous inspirer des catégories de questions affichées ci-dessous.",
    "Les catégories ci-dessous vous permettent aussi de découvrir mes fonctionnalités.",
]


def _salutation(current_hour: int | None = None) -> Text:
    # Emoji uniquement ici (seul endroit autorise dans tout le message
    # d'accueil) : 18h-04h59 partage desormais la meme salutation "Bonsoir"
    # (auparavant "Bonne nuit" apres 22h, distinction retiree a la demande).
    hour = current_hour if current_hour is not None else datetime.now().hour

    if 5 <= hour < 12:
        return "Bonjour 👋"
    if 12 <= hour < 18:
        return "Bon après-midi 👋"
    return "Bonsoir 👋"


def build_greeting_message(current_hour: int | None = None, include_faq_closing: bool = True) -> Text:
    capabilities = _join_naturally([c.description for c in AGENT_CAPABILITIES])
    invite = random.choice(_INVITATION_VARIANTS)
    if include_faq_closing:
        # Omis si aucune categorie n'a pu etre recuperee (voir
        # ActionGreetWithTime) : ne jamais promettre des exemples de
        # questions "ci-dessous" qui ne s'afficheront pas.
        invite = f"{invite} {random.choice(_CLOSING_VARIANTS)}"
    return "\n\n".join(
        [
            f"{_salutation(current_hour)} {random.choice(_WELCOME_VARIANTS)}",
            "Je suis l'assistant virtuel de NGONI.",
            f"Je peux notamment {capabilities}.",
            invite,
        ]
    )


class ActionGreetWithTime(Action):

    def name(self) -> Text:
        return "action_greet_with_time"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        # Les categories FAQ sont affichees directement ici (boutons de
        # categorie, voir fetch_faq_category_buttons dans faq.py) plutot que
        # derriere un bouton "Voir des questions" a cliquer d'abord -- retour
        # utilisateur : elles devaient etre visibles des la salutation, pas
        # apres une etape intermediaire. Toujours un seul utter_message : la
        # reponse HTTP du webhook REST ne contient qu'un seul objet message
        # pour ce tour, rien qu'un client puisse etaler dans le temps pour
        # simuler un effet "streaming".
        buttons, cache_events = fetch_faq_category_buttons(tracker)
        dispatcher.utter_message(
            text=build_greeting_message(include_faq_closing=bool(buttons)),
            buttons=buttons or [],
        )
        return cache_events
