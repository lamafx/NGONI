import random
import re
from os import getenv
from typing import Optional, Text

import requests
from rasa_sdk import Tracker


def pick(*variants: Text) -> Text:
    """Tire une formulation au hasard parmi plusieurs, toutes factuellement
    equivalentes (voir greeting.py, _WELCOME_VARIANTS et consorts, premier
    endroit ou ce principe a ete introduit) : seul l'habillage change d'un
    appel a l'autre, jamais le contenu. Centralise ici pour que
    reclamation.py/diagnostic.py n'aient pas chacun leur propre
    random.choice(...) disperse.
    """
    return random.choice(variants)

FAQ_SERVICE_URL = getenv("FAQ_SERVICE_URL", "http://fastapi:8000/faq/search")

# Coordonnees affichees a l'utilisateur quand le bot echoue trop de fois de
# suite a comprendre sa demande (voir _consecutive_fallback_count /
# _human_support_message ci-dessous) -- configurables par environnement,
# jamais codees en dur dans le message lui-meme.
SUPPORT_CONTACT_EMAIL = getenv("SUPPORT_CONTACT_EMAIL", "support@ngoni.com")
SUPPORT_CONTACT_PHONE = getenv("SUPPORT_CONTACT_PHONE", "+225 00 00 00 00")

# Actions considerees comme un "fallback" du point de vue de l'utilisateur :
# le bot n'a pas su repondre a la demande, que la cause soit une confiance
# NLU trop faible (action_default_fallback) ou une intention hors-sujet
# (action_out_of_scope) -- regroupees dans un seul compteur, les deux
# vehiculent la meme experience ("le bot ne m'aide pas").
FALLBACK_ACTION_NAMES = {"action_default_fallback", "action_out_of_scope"}

# Nombre de fallbacks consecutifs a partir duquel on oriente l'utilisateur
# vers le support humain plutot que de repeter un message generique.
FALLBACK_ESCALATION_THRESHOLD = 3


def _consecutive_fallback_count(tracker: Tracker) -> int:
    """Compte les fallbacks consecutifs en remontant l'historique brut de la
    conversation (tracker.events) jusqu'a la premiere action qui n'en est pas
    un. tracker.events n'est jamais modifie par un evenement "rewind" (qui
    n'affecte que la reconstruction d'etat des policies, pas le journal brut)
    -- meme principe deja utilise par _already_ran_since_last_user_message
    ci-dessous et par ActionDefaultFallback (diagnostic.py), qui exclut deja
    explicitement son propre nom lors d'un scan similaire : l'action en cours
    d'execution est deja le dernier evenement "action" du tracker au moment
    ou run() s'execute (constate en pratique), donc incluse ici dans le
    compte plutot qu'exclue.
    """
    count = 0
    for event in reversed(tracker.events):
        if event.get("event") != "action":
            continue
        name = event.get("name")
        if name == "action_listen":
            continue
        if name in FALLBACK_ACTION_NAMES:
            count += 1
            continue
        break
    return count


def _human_support_message() -> Text:
    return (
        "Je rencontre des difficultés à comprendre votre demande depuis plusieurs messages. "
        "Pour éviter de vous faire perdre du temps, vous pouvez contacter directement notre "
        f"équipe support : {SUPPORT_CONTACT_EMAIL} ou {SUPPORT_CONTACT_PHONE}."
    )

# Sous ce nombre de mots, un segment se terminant par "?" est trop court
# pour etre une vraie question FAQ (ex. un "?" isole, ou une interjection).
MIN_TRAILING_QUESTION_WORDS = 3

# Cause racine (bug "Bonsoir comment allez-vous ? J'ai fait un retrait...") :
# la classification diagnostic (voir diagnostic.py, _score_capabilities*)
# fonctionne par similarite d'embedding sur le texte entier. Un preambule de
# politesse fait la moyenne du vecteur avec le vrai contenu et peut faire
# passer un message pourtant clair sous le seuil de similarite -- constate en
# pratique, pas seulement theorique. La segmentation par ponctuation forte
# (_segment_message cote diagnostic.py) attenue ce risque mais seulement si
# l'utilisateur separe la salutation du reste par un ".", "!" ou "?" -- une
# virgule ("Bonsoir, j'ai un probleme...") ou aucune ponctuation ne
# declenchent aucune segmentation, laissant la salutation diluer le message
# entier. Retirer ce preambule AVANT toute classification, quel que soit ce
# qui suit, ferme ce trou independamment de la ponctuation utilisee.
#
# Ancre en debut de chaine (^) uniquement : un "bonjour" mentionne ailleurs
# dans le message (rare mais possible) n'est jamais touche.
_GREETING_TOKEN = r"(?:bonjour|bonsoir|salut|coucou|hello|hey)"
_COURTESY_TOKEN = (
    r"(?:comment\s+(?:allez[-\s]vous|vas[-\s]tu|tu\s+vas|(?:ça|ca)\s+va)|(?:ça|ca)\s+va)\s*\??"
)
_GREETING_PREAMBLE_PATTERN = re.compile(
    rf"^\s*(?:{_GREETING_TOKEN}\s*[,;.!?]*\s*(?:{_COURTESY_TOKEN})?|{_COURTESY_TOKEN})\s*[,;.!?]*\s*",
    re.IGNORECASE,
)


def _strip_greeting_preamble(text: Text) -> Text:
    """Retire un preambule de politesse en debut de message (salutation seule
    ou suivie d'une formule du type "comment allez-vous ?"), pour que la
    classification qui suit ne travaille que sur le contenu utile.

    Si le message est ENTIEREMENT une salutation (rien apres retrait), le
    texte original est retourne inchange : ce cas reste gere par le flux
    d'accueil existant, pas par cette fonction.
    """
    stripped = _GREETING_PREAMBLE_PATTERN.sub("", text, count=1)
    if not stripped.strip():
        return text
    return stripped


def _extract_trailing_faq_question(text: Text) -> Optional[Text]:
    """Audit "robustesse comportementale", cas 9/10 : un message peut
    melanger un diagnostic ou une reclamation avec une question FAQ
    distincte ("Pourquoi mon retrait est bloqué ? Au fait comment fonctionne
    le système de pièces ?", "Je veux porter plainte. Au fait c'est quoi le
    KYC ?"). Marqueur purement grammatical (point d'interrogation), pas un
    mot-cle metier : ne suppose rien du SUJET de la question, seulement
    qu'elle forme un segment syntaxiquement distinct du reste du message
    (au moins un autre segment avant elle).
    """
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    if len(pieces) < 2 or not pieces[-1].endswith("?"):
        return None
    trailing = pieces[-1]
    if len(trailing.split()) < MIN_TRAILING_QUESTION_WORDS:
        return None
    return trailing


def _search_faq(question: Text) -> Optional[Text]:
    # Reutilise le meme service que ActionFaqSearch (voir faq.py), en
    # silencieux : une panne ou une absence de reponse ici ne doit pas
    # perturber le flux principal (diagnostic/reclamation) auquel cette
    # question residuelle est seulement ajoutee en complement.
    try:
        response = requests.post(FAQ_SERVICE_URL, json={"question": question}, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        return None
    # Audit FAQ : /faq/search ne renvoie plus answer pour un score sous le
    # seuil (voir find_best_answer cote FastAPI), mais on verifie aussi
    # flow.status explicitement ici, en defense supplementaire -- cette
    # fonction est un point d'entree direct au service FAQ pour une question
    # residuelle non classifiee par Rasa (contrairement a ActionFaqSearch,
    # qui n'est appelee qu'apres une classification ask_faq confiante), donc
    # une garde locale plutot que de dependre entierement du contrat cote
    # serveur.
    if payload.get("flow", {}).get("status") != "matched":
        return None
    return payload.get("answer") or payload.get("response") or payload.get("result")


def _already_ran_since_last_user_message(tracker: Tracker, action_name: Text) -> bool:
    # Filet de securite independant des policies Rasa : meme apres avoir
    # consolide des actions chainees en une seule (voir docstring de
    # ActionRunDiagnosticStep), TEDPolicy peut encore, sur certains
    # historiques, predire une 2e execution de cette action sans nouveau
    # message utilisateur entre les deux (constate en pratique avec une
    # confiance > 0.9, malgre une regle qui la fait deja tourner une 1ere
    # fois a confiance 1.0). Plutot que de continuer a chasser ce
    # comportement cote policies/stories, on le rend inoffensif ici : si
    # cette action a deja tourne depuis le dernier message utilisateur, on ne
    # fait rien la 2e fois.
    for event in reversed(tracker.events):
        if event.get("event") == "user":
            return False
        if event.get("event") == "action" and event.get("name") == action_name:
            return True
    return False
