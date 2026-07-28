import random
from datetime import datetime
from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

from .capabilities import AGENT_CAPABILITIES, _join_naturally
from .common import QUICK_ACTION_BUTTONS
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

# Accueil raccourci pour un utilisateur qui a deja ete salue au moins une fois
# (voir _has_greeted_before) : re-expliquer "je suis l'assistant virtuel de
# NGONI, je peux notamment..." a l'identique a CHAQUE retour est redondant --
# feuille de route UX (2026-07), point A4. Le detail des capacites reste a
# une commande de distance (ask_capabilities) pour qui en a besoin.
_WELCOME_BACK_VARIANTS = [
    "Re-bonjour, content de vous revoir 👋",
    "Ravi de vous retrouver 👋",
    "Bonjour, heureux de vous revoir par ici 👋",
]

_WELCOME_BACK_INVITATION_VARIANTS = [
    "Comment puis-je vous aider aujourd'hui ?",
    "Qu'est-ce qui vous amène cette fois-ci ?",
    "Je suis à votre écoute, que puis-je faire pour vous ?",
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


def build_greeting_message(
    current_hour: int | None = None, include_faq_closing: bool = True, returning: bool = False
) -> Text:
    if returning:
        invite = random.choice(_WELCOME_BACK_INVITATION_VARIANTS)
        if include_faq_closing:
            invite = f"{invite} {random.choice(_CLOSING_VARIANTS)}"
        return "\n\n".join([random.choice(_WELCOME_BACK_VARIANTS), invite])

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


# Nombre de categories FAQ affichees des l'accueil (feuille de route UX,
# 2026-07, point A3) : jusqu'a 10 categories (voir FAQ_SUGGESTIONS_COUNT,
# faq.py) plus les 2 boutons d'action rapide donnaient jusqu'a 12 boutons
# d'un coup sur le tout premier message -- un mur de choix, pas une
# selection soignee. fetch_faq_category_buttons reste inchangee (partagee
# avec ActionBrowseFaq, ou afficher davantage de choix sur une demande
# EXPLICITE "montre-moi des questions" reste pertinent) : le tri ne se fait
# qu'ici, cote affichage de l'accueil.
GREETING_FAQ_BUTTON_LIMIT = 4


def _has_greeted_before(tracker: Tracker) -> bool:
    """True si action_greet_with_time a deja tourne au moins une fois AVANT
    le message utilisateur qui vient de declencher cet appel -- le tracker
    store etant persistant (Postgres, voir endpoints.yml), cet historique
    survit aux redemarrages et couvre donc de vraies sessions anterieures,
    pas seulement le tour precedent. Cherche strictement AVANT le dernier
    evenement "user" (plutot que sur tracker.events en entier) pour rester
    correct que cette execution-ci soit deja inscrite au tracker recu ou non
    -- les deux comportements ont ete constates selon le contexte
    d'invocation ailleurs dans ce fichier (voir _consecutive_fallback_count,
    common.py), donc jamais suppose implicitement ici.
    """
    events = tracker.events
    last_user_idx = None
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("event") == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        return False
    return any(
        e.get("event") == "action" and e.get("name") == "action_greet_with_time"
        for e in events[:last_user_idx]
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
        #
        # Suggestions d'actions des l'ouverture (experience conversationnelle,
        # 2026-07) : les 2 premiers boutons de QUICK_ACTION_BUTTONS (diagnostic
        # / reclamation, voir common.py) sont places AVANT les categories FAQ,
        # qui remplissent deja a elles seules le role du 3e ("Voir la FAQ"
        # generique serait redondant avec des categories reelles deja
        # visibles) -- pas de bouton FAQ supplementaire ici. Categories FAQ
        # tronquees a GREETING_FAQ_BUTTON_LIMIT (voir sa docstring) pour ne
        # pas noyer ces 2 boutons dans un mur de choix.
        faq_buttons, cache_events = fetch_faq_category_buttons(tracker)
        shown_faq_buttons = (faq_buttons or [])[:GREETING_FAQ_BUTTON_LIMIT]
        returning = _has_greeted_before(tracker)
        dispatcher.utter_message(
            text=build_greeting_message(include_faq_closing=bool(shown_faq_buttons), returning=returning),
            buttons=QUICK_ACTION_BUTTONS[:2] + shown_faq_buttons,
        )
        return cache_events
