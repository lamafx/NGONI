import json
import logging
import re
import threading
import time
import uuid
from os import getenv
from typing import Any, Dict, List, Optional, Text

import requests
from rasa_sdk import Action, Tracker

# Audit observabilite : voir le meme commentaire dans diagnostic.py.
logger = logging.getLogger(__name__)
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.forms import FormValidationAction

from .common import (
    QUICK_ACTION_BUTTONS,
    _already_ran_since_last_user_message,
    _extract_trailing_faq_question,
    _search_faq,
    pick,
    request_with_retry,
)
from .diagnostic import _call_diagnostic_engine, _cosine_similarity, _embed_message, _embed_messages

TICKET_SERVICE_URL = getenv("TICKET_SERVICE_URL", "http://fastapi:8000/tickets/create")
TICKET_LIST_SERVICE_URL = getenv("TICKET_LIST_SERVICE_URL", "http://fastapi:8000/complaints/mine")

# Etoffe (retour utilisateur, 2026-07) au-dela des formes nominales
# d'origine ("connexion", "vérification"...) pour couvrir aussi les formes
# verbales courantes d'une description libre ("je n'arrive pas a me
# CONNECTER", "je veux RECHARGER mon compte") : plus cette liste couvre de
# formulations naturelles, moins souvent _infer_category_from_description
# (voir plus bas) doit retomber sur la question explicite de categorie.
CATEGORY_KEYWORDS: Dict[Text, List[Text]] = {
    "KYC": ["kyc", "identité", "identite", "document", "vérification", "verification", "pièce d'identité", "piece d'identite"],
    "Wallet": ["wallet", "porte-monnaie", "porte monnaie", "pièce", "piece", "retrait", "argent", "solde", "paiement", "payer", "recharge", "recharger"],
    "Video": ["vidéo", "video", "live", "diffusion"],
    "Auth": ["connexion", "connecter", "login", "auth", "mot de passe", "password", "identifiant", "accès", "acces"],
    "Chat": ["chat", "message", "messagerie", "discussion"],
    "Safety": ["sécurité", "securite", "abus", "harcèl", "harcel", "safety", "insulte", "menace", "inapproprié", "inapproprie"],
}

DEVICE_KEYWORDS: Dict[Text, List[Text]] = {
    "mobile": ["téléphone", "telephone", "mobile", "android", "iphone"],
    "ordinateur": ["ordinateur", "pc"],
}

ERROR_TYPE_KEYWORDS: Dict[Text, List[Text]] = {
    "bloqué": ["bloqué", "bloque"],
    "erreur": ["bug", "erreur"],
    "non fonctionnel": ["ne fonctionne pas", "ne marche pas"],
}

# Audit qualite du code, cas #1 : device/error_type etaient purement
# a base de mots-cles (best_keyword_match), rate silencieusement toute
# reformulation absente des listes ci-dessus (ex. "ca plante" pour
# "erreur", "je suis coince" pour "bloqué"). Ces 2 champs sont de la
# METADONNEE de ticket (jamais valides par l'utilisateur ni utilises pour
# brancher le flux, contrairement a `category` qui reste un slot Form avec
# enum strict) : un faux classement ici mal-etiquette un ticket sans casser
# la conversation, ce qui justifie un repli mots-cles en filet de securite
# plutot qu'un blocage. Memes phrases d'exemple que catalogue diagnostic :
# embeddees UNE fois (voir _semantic_example_embeddings, cache sans TTL --
# contrairement a _capabilities_cache, ces phrases ne changent jamais entre
# deux deploiements) puis comparees par similarite cosinus au texte libre.
SEMANTIC_FIELD_EXAMPLES: Dict[Text, Dict[Text, List[Text]]] = {
    "device": {
        "mobile": ["sur mon téléphone", "depuis mon mobile", "sur mon smartphone"],
        "ordinateur": ["sur mon ordinateur", "depuis mon pc", "sur mon laptop"],
    },
    "error_type": {
        "bloqué": ["c'est bloqué", "ça ne débloque pas", "je suis coincé", "impossible d'avancer"],
        "erreur": ["il y a un bug", "une erreur s'affiche", "ça plante", "message d'erreur"],
        "non fonctionnel": ["ça ne fonctionne pas", "ça ne marche pas du tout", "rien ne se passe"],
    },
}

# CALIBRAGE (14 messages reels : 9 avec signal reel, 5 sans aucun rapport
# avec le champ teste) -- meme phenomene que documente pour
# CLASSIFICATION_RELATIVE_MARGIN plus haut : ce modele resserre TOUTES les
# similarites vers 0.85-0.95 sur des phrases courtes, y compris pour un
# texte totalement hors-sujet (ex. "je ne sais pas" scorait 0.881 contre
# "ordinateur"). Un seuil a 0.80 (premiere estimation, non calibree)
# laissait passer ces faux positifs. Observe avec le score du MEILLEUR
# label sur chaque champ :
#   Vrais signaux    : 0.9516 / 0.8921 / 0.9377 / 0.9801 / 0.9609 / 0.9428 / 0.9267 / 0.9229
#   Hors-sujet       : 0.8635 / 0.8786 / 0.881  / 0.8939 / 0.8979 / 0.8717
# 0.90 separe proprement les deux groupes sur cet echantillon. A reaffiner
# si l'usage reel montre un groupe different de ces 14 exemples.
MIN_FIELD_SEMANTIC_SIMILARITY = 0.90

_semantic_example_embeddings: Dict[Text, Dict[Text, List[List[float]]]] = {}
_semantic_example_lock = threading.Lock()


def _get_semantic_example_embeddings(field: Text) -> Dict[Text, List[List[float]]] | None:
    # Cache permanent (pas de TTL, voir commentaire ci-dessus) protege par
    # verrou pour eviter que deux requetes concurrentes n'embeddent chacune
    # tout le catalogue d'exemples au demarrage (meme principe que
    # _fetch_capabilities, cas #5). None = panne reseau au tout premier
    # appel : aucun cache a retomber dessus, l'appelant bascule sur les
    # mots-cles pour cette requete.
    if field in _semantic_example_embeddings:
        return _semantic_example_embeddings[field]
    with _semantic_example_lock:
        if field in _semantic_example_embeddings:
            return _semantic_example_embeddings[field]
        labels = list(SEMANTIC_FIELD_EXAMPLES[field].keys())
        all_examples = [SEMANTIC_FIELD_EXAMPLES[field][label] for label in labels]
        flat_examples = [example for examples in all_examples for example in examples]
        flat_embeddings = _embed_messages(flat_examples)
        if not flat_embeddings:
            return None
        embeddings_by_label: Dict[Text, List[List[float]]] = {}
        cursor = 0
        for label, examples in zip(labels, all_examples):
            embeddings_by_label[label] = flat_embeddings[cursor : cursor + len(examples)]
            cursor += len(examples)
        _semantic_example_embeddings[field] = embeddings_by_label
        return embeddings_by_label


def _best_semantic_match(field: Text, text: Text, keyword_map: Dict[Text, List[Text]], default: Text) -> Text:
    examples_by_label = _get_semantic_example_embeddings(field)
    text_embedding = _embed_message(text) if examples_by_label else None
    if examples_by_label and text_embedding is not None:
        scores = {
            label: max(_cosine_similarity(text_embedding, example) for example in examples)
            for label, examples in examples_by_label.items()
        }
        best_label, best_score = max(scores.items(), key=lambda item: item[1])
        if best_score >= MIN_FIELD_SEMANTIC_SIMILARITY:
            return best_label
    # Repli mots-cles : panne reseau, embeddings pas encore charges, ou aucun
    # label assez proche semantiquement -- garde le comportement existant
    # (deja teste en production) comme filet de securite plutot que de
    # renvoyer `default` a tort.
    return best_keyword_match(text, keyword_map, default)

# Reponse a "quel champ voulez-vous modifier ?" (voir validate_field_to_edit) :
# associe chaque mot-cle au NOM DU SLOT concerne (pas un libelle affichable),
# pour pouvoir le mettre a None directement et laisser reclamation_form le
# redemander via son propre utter_ask_<slot>.
FIELD_TO_EDIT_KEYWORDS: Dict[Text, List[Text]] = {
    "category": ["categorie", "catégorie", "service", "type"],
    "description": ["description", "detail", "détail", "probleme", "problème"],
    "incident_date": ["date", "quand", "jour"],
}

# Reponse a "modifier ou annuler ?" (voir validate_cancel_choice).
# Interpretee par mots-cles plutot que par intention NLU : deny possede deja
# des dizaines d'exemples entraines contenant "annule"/"corrige"/"modifier"
# (utiles pour detecter un refus a la confirmation), donc des intentions
# separees pour ce choix entraient en collision avec deny au moment de
# l'entrainement -- constate en pratique : "non" seul finissait classe
# confirm_full_cancel a plus de 99% de confiance au lieu de deny, cassant la
# question de clarification elle-meme des le premier "non". from_text (voir
# le slot cancel_choice dans domain.yml) evite totalement ce risque.
CANCEL_CHOICE_KEYWORDS: Dict[Text, List[Text]] = {
    "edit": ["modifier", "corriger", "changer", "rectifier", "editer", "éditer"],
    "cancel": ["annuler", "annule", "supprimer", "abandonner", "effacer"],
}

# Audit "robustesse comportementale", cas 38/39 : aucun plafond haut
# n'existait sur les champs libres avant ce fix (seul un plancher de 20
# caracteres protegeait validate_description). Un champ libre sans limite
# est une surface d'epuisement de ressources triviale (formulaire boucle,
# chaque tentative stockant/traitant un texte arbitrairement long).
MAX_DESCRIPTION_LENGTH = 2000
# incident_date n'a jamais de raison legitime d'etre long (une vraie reponse
# tient en quelques mots) : au-dela, on rejette plutot que de tronquer --
# contrairement a description, un incident_date tronque n'aurait aucun sens
# a stocker.
MAX_INCIDENT_DATE_LENGTH = 200

# Audit "robustesse comportementale", cas 23 : une menace ("je vais vous
# denoncer", "je vais porter plainte") n'a pas besoin d'un routage special
# -- create_reclamation la capte deja correctement -- mais un agent humain
# qui reprend le ticket plus tard n'a aucun signal qu'il doit adapter son
# ton avant meme d'ouvrir la description. Prefixe la description plutot
# qu'un nouveau champ de payload (ticket_source a deja un role different,
# et rien ne garantit que /tickets/create accepte un champ inconnu sans
# erreur de validation cote FastAPI).
# Audit qualite du code, cas #2 : passage a l'embedding envisage puis non
# retenu ici aussi, par analogie avec la mesure faite cote diagnostic.py sur
# _looks_like_resolution/_looks_like_refusal/_looks_like_uncertain (meme
# modele, meme resserrement des similarites sur phrases courtes en
# francais, voir le detail chiffre la-bas). Risque different ici (un faux
# positif ajoute juste un prefixe au ticket, ne fait perdre aucune
# information) mais rien n'indique que la limite du modele constatee
# ailleurs ne s'appliquerait pas de la meme façon a ces locutions.
_THREAT_PHRASES = (
    "je vais vous dénoncer", "je vais vous denoncer",
    "je vais porter plainte", "je vais deposer plainte",
    "je vais signaler ça", "je vais signaler ca",
    "je vais alerter les autorités", "je vais alerter les autorites",
    "je vais vous poursuivre", "je vais aller voir la presse",
    "je vais prévenir les médias", "je vais prevenir les medias",
)


def _looks_like_threat(text: Text) -> bool:
    normalized = text.lower()
    return any(phrase in normalized for phrase in _THREAT_PHRASES)


# validate_incident_date acceptait n'importe quelle chaine non vide ("asdf"
# aussi valide que "hier"). Heuristique volontairement sans dependance
# externe (dateutil n'est pas installe dans l'image actions -- l'ajouter
# demanderait un rebuild d'image, hors scope d'un correctif qui ne doit pas
# necessiter de reentrainement/redeploiement lourd) : rejette au moins le
# texte qui ne ressemble a aucune date, plutot qu'une validation stricte.
#
# Comparaison par SOUS-CHAINE (mot-cle contenu dans le texte), pas par
# egalite stricte : une premiere version comparait le texte normalise ENTIER
# a cet ensemble (`normalized in _RELATIVE_DATE_KEYWORDS`), ce qui rejetait
# "hier soir" ou "ce soir" -- pourtant aussi naturels que "hier" ou "ce
# matin" -- simplement parce que la phrase entiere ne matchait aucune entree
# EXACTE. Trouve par test conversationnel (505 tours, 2026-07-18) : une fois
# ce rejet declenche, le formulaire reste bloque sur cette question pour de
# bon (tout message suivant, meme sans rapport avec une date, est revalide
# de la meme facon et rejete a son tour -- aucune echappatoire). Le passage
# en sous-chaine beneficie aussi gratuitement de variantes comme "avant-hier
# soir" (deja une sous-chaine de "avant-hier").
_RELATIVE_DATE_KEYWORDS = {
    "aujourd'hui", "aujourd hui", "hier", "avant-hier", "avant hier",
    "ce matin", "cette nuit", "cette semaine",
    # "la semaine derniere" (forme accentuee manquante avant -- grande vague
    # de tests conversationnels, 2026-07) : _looks_like_a_date ne compare
    # que via .lower(), qui ne retire pas les accents. "la semaine
    # dernière" (avec accent, la forme naturelle en francais) ne matchait
    # jamais l'entree sans accent seule -- meme raisonnement pour "recemment".
    "la semaine derniere", "la semaine dernière",
    "le mois dernier", "recemment", "récemment",
    # Ajoutes suite au meme audit : "ce soir" ne contient aucun des mots-cles
    # ci-dessus (contrairement a "hier soir", deja couvert via "hier").
    "ce soir", "cet après-midi", "cet apres-midi", "cette après-midi", "cette apres-midi",
    "la nuit dernière", "la nuit derniere", "le week-end dernier", "le weekend dernier",
    "ce week-end", "ce weekend", "tout à l'heure", "tout a l'heure",
    "en fin de journée", "en fin de journee", "en fin d'après-midi", "en fin d'apres-midi",
    # Audit qualite NLU : nlu.yml enseigne desormais des exemples incident_date
    # avec un jour de semaine seul ("lundi") ou qualifie ("mardi dernier") --
    # sans cette entree, l'extraction NLU aurait reussi mais la validation
    # aurait quand meme rejete la reponse, exactement le meme bug que celui
    # deja corrige pour "la semaine derniere" (voir plus haut). Sous-chaine
    # (comme le reste de cet ensemble) : couvre gratuitement "lundi dernier",
    # "mardi prochain", etc.
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
}
_MONTH_NAMES = {
    "janvier", "fevrier", "février", "mars", "avril", "mai", "juin",
    "juillet", "aout", "août", "septembre", "octobre", "novembre",
    "decembre", "décembre",
}
_DATE_LIKE_PATTERN = re.compile(
    r"\d{1,2}\s*[/\-.]\s*\d{1,2}(\s*[/\-.]\s*\d{2,4})?"  # 03/07, 03-07-2026
    r"|\d{4}-\d{2}-\d{2}"  # 2026-07-03
    r"|il y a\b"  # "il y a deux jours"
)


def _looks_like_a_date(text: Text) -> bool:
    normalized = text.strip().lower()
    if any(keyword in normalized for keyword in _RELATIVE_DATE_KEYWORDS):
        return True
    if _DATE_LIKE_PATTERN.search(normalized):
        return True
    if any(month in normalized for month in _MONTH_NAMES) and any(ch.isdigit() for ch in normalized):
        return True
    return False

# Table de correspondance insensible a la casse (remplace une boucle
# for/if comparant chaque valeur autorisee une a une dans validate_category).
ALLOWED_CATEGORIES: Dict[Text, Text] = {
    "kyc": "KYC",
    "identité": "KYC",
    "identite": "KYC",
    "vérification": "KYC",
    "verification": "KYC",
    "wallet": "Wallet",
    "portefeuille": "Wallet",
    "porte-monnaie": "Wallet",
    "porte monnaie": "Wallet",
    "video": "Video",
    "vidéo": "Video",
    "vidéos": "Video",
    "videos": "Video",
    "auth": "Auth",
    "connexion": "Auth",
    "authentification": "Auth",
    "login": "Auth",
    "chat": "Chat",
    "messagerie": "Chat",
    "messages": "Chat",
    "safety": "Safety",
    "sécurité": "Safety",
    "securite": "Safety",
}

# Audit ton/clarite : le statut backend (voir complaints/schemas.py::ALLOWED_STATUSES)
# etait affiche brut a l'utilisateur ("OPEN" en majuscules anglaises) dans le
# message de confirmation de ticket.
TICKET_STATUS_LABELS: Dict[Text, Text] = {
    "OPEN": "ouvert",
    "IN_PROGRESS": "en cours",
    "RESOLVED": "résolu",
    "CLOSED": "clôturé",
}

# Le slot categoriel "category" (domain.yml) maintient sa propre liste de
# valeurs autorisees, dupliquee par necessite (Rasa ne peut pas lire ce
# dict Python au chargement du domaine). Cette verification echoue au
# demarrage de l'action server si les deux divergent, plutot que de laisser
# une categorie ajoutee d'un cote seulement casser silencieusement soit la
# validation ici, soit le slot Rasa.
#
# Audit robustesse : un `assert` nu est desactive des que l'interpreteur
# tourne avec -O/PYTHONOPTIMIZE=1 (la ligne est litteralement retiree du
# bytecode) -- la garantie "echoue au demarrage plutot que de casser
# silencieusement" ne tenait plus dans ce cas, sans qu'aucun test ne le
# detecte. Une verification explicite qui leve elle-meme reste active quel
# que soit le niveau d'optimisation Python.
_DOMAIN_CATEGORY_VALUES = {"KYC", "Wallet", "Video", "Auth", "Chat", "Safety"}
if set(ALLOWED_CATEGORIES.values()) != _DOMAIN_CATEGORY_VALUES:
    raise RuntimeError(
        "ALLOWED_CATEGORIES (reclamation.py) et les values: du slot 'category' "
        "(domain.yml) ont diverge -- synchronisez les deux."
    )


class _TicketServiceCircuitBreaker:
    # Etat en memoire du process actions, pas partage entre plusieurs workers
    # ni persistant entre redemarrages : suffisant ici (le but n'est pas une
    # garantie distribuee mais d'eviter de faire attendre 10s (timeout de
    # requests.post) chaque utilisateur pendant une panne prolongee du
    # service de tickets, une fois que plusieurs echecs consecutifs l'ont
    # rendu probable). Contrairement au disjoncteur du pipeline diagnostic
    # (fastapi/app/domains/diagnostic/circuit_breaker.py), celui-ci ne peut
    # pas etre reutilise tel quel : action server (ce process) et fastapi
    # sont deux conteneurs/codebases separes, sans import partage possible.
    # Meme limite multi-replicas que _TicketRateLimiter ci-dessous (voir son
    # commentaire "LIMITE CONNUE") : chaque replica ouvrirait son propre
    # disjoncteur independamment, avec le meme seuil FAILURE_THRESHOLD
    # applique par instance plutot que globalement -- ici l'impact est
    # moindre (retarder la detection d'une panne, pas une garantie de
    # securite contournee).
    FAILURE_THRESHOLD = 3
    COOLDOWN_SECONDS = 30

    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._opened_at: Optional[float] = None
        # Audit robustesse : sans ce verrou, deux requetes concurrentes
        # (deux utilisateurs distincts, meme process actions) qui echouent en
        # meme temps peuvent toutes deux lire _consecutive_failures avant que
        # l'une n'ecrive son incrementation -- un echec perdu (read-modify-write
        # non atomique), retardant l'ouverture reelle du disjoncteur. Meme
        # principe que _capabilities_lock (diagnostic.py).
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self.COOLDOWN_SECONDS:
                # Cooldown ecoule : on retente (etat "half-open" implicite) au
                # lieu de rester ouvert indefiniment jusqu'a un redemarrage.
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.FAILURE_THRESHOLD:
                self._opened_at = time.monotonic()


_ticket_circuit_breaker = _TicketServiceCircuitBreaker()


class _TicketRateLimiter:
    # Meme limite (etat en memoire, par process) que le disjoncteur ci-dessus.
    # Rien n'empechait auparavant un meme sender_id de creer un nombre
    # illimite de tickets en boucle (bug de dialogue ou volontaire), exposant
    # la file de support a un engorgement.
    #
    # Audit qualite du code, cas #6 -- LIMITE CONNUE, PAS CORRIGEE ICI :
    # `_timestamps_by_user` (comme `_ticket_circuit_breaker` ci-dessus) vit
    # dans la memoire d'UN SEUL process Python. Aujourd'hui (1 seul conteneur
    # `actions`, voir docker-compose.yml) la limite ci-dessous (3
    # tickets/heure/utilisateur) est donc bien celle reellement appliquee.
    # Des que ce conteneur est scale horizontalement (plusieurs replicas,
    # ou plusieurs workers Sanic dans le meme process) OU redemarre en cours
    # de fenetre, cette garantie casse silencieusement :
    #   - Plusieurs replicas : chaque instance tient son propre compteur
    #     independant pour le meme sender_id -- la limite REELLE devient
    #     MAX_TICKETS_PER_WINDOW x (nombre de replicas), pas 3, sans qu'aucun
    #     log ne signale la difference.
    #   - Redemarrage/redeploiement : `_timestamps_by_user` repart a zero,
    #     un utilisateur au plafond juste avant peut recreer 3 tickets de
    #     plus juste apres.
    # Corriger cela correctement demande un compteur PARTAGE entre
    # instances (ex. Redis avec `INCR` + `EXPIRE`, ou une table Postgres
    # dediee) -- hors de portee d'un simple changement de code ici, ca
    # demanderait d'ajouter une dependance d'infrastructure au service
    # actions. Documente comme limite connue plutot que corrige a moitie.
    MAX_TICKETS_PER_WINDOW = 3
    WINDOW_SECONDS = 3600

    def __init__(self) -> None:
        self._timestamps_by_user: Dict[Text, List[float]] = {}
        # Audit robustesse : sans ce verrou, deux requetes concurrentes pour
        # le MEME sender_id (ex. double-clic, ou deux onglets) peuvent toutes
        # deux appeler allow() avant que l'une n'appelle record() -- chacune
        # lit le meme compte encore sous le plafond et l'autorise, permettant
        # de depasser MAX_TICKETS_PER_WINDOW sur une seule instance, meme sans
        # le probleme multi-replica documente ci-dessus.
        self._lock = threading.Lock()

    def allow(self, user_id: Text) -> bool:
        with self._lock:
            now = time.monotonic()
            recent = [t for t in self._timestamps_by_user.get(user_id, []) if now - t < self.WINDOW_SECONDS]
            self._timestamps_by_user[user_id] = recent
            return len(recent) < self.MAX_TICKETS_PER_WINDOW

    def record(self, user_id: Text) -> None:
        with self._lock:
            self._timestamps_by_user.setdefault(user_id, []).append(time.monotonic())


_ticket_rate_limiter = _TicketRateLimiter()


def best_keyword_match(text: Text, keyword_map: Dict[Text, List[Text]], default: Text) -> Text:
    # Score chaque categorie sur son nombre de mots-cles presents plutot que de
    # s'arreter a la premiere qui matche : evite qu'une categorie plus haute
    # dans une chaine if/elif "gagne" a tort quand plusieurs mots-cles de
    # categories differentes apparaissent dans le meme message.
    #
    # Audit robustesse : `kw in text` matchait par simple sous-chaine, sans
    # limite de mot -- contrairement a _keyword_matches (diagnostic.py), qui
    # utilise deja \b...\b precisement pour eviter ce probleme. Exemple reel :
    # "j'ai fait un achat, mon solde n'a pas change" faisait matcher le
    # mot-cle Chat "chat" dans la sous-chaine "achat", pouvant faire basculer
    # `category` vers Chat au lieu de Wallet -- silencieusement, la categorie
    # deduite n'est jamais reconfirmee a l'utilisateur.
    scores = {
        label: sum(1 for kw in keywords if re.search(rf"\b{re.escape(kw.lower())}\b", text))
        for label, keywords in keyword_map.items()
    }
    best_label, best_score = max(scores.items(), key=lambda item: item[1])
    return best_label if best_score > 0 else default


def _infer_category_from_description(normalized_text: Text) -> Optional[Text]:
    """Tente de deduire la categorie (KYC/Wallet/Video/Auth/Chat/Safety)
    directement depuis la description libre de l'utilisateur, pour eviter de
    lui demander explicitement de choisir un "service" -- ce jargon (des noms
    d'architecture interne, pas du vocabulaire utilisateur) ne veut rien dire
    pour un public qui ne maitrise pas la plateforme (retour utilisateur,
    2026-07 : "quel est le service concerne ça n'aide pas"). Utilisee par
    validate_description ci-dessous, juste apres que la description ait ete
    acceptee -- None si aucun mot-cle de CATEGORY_KEYWORDS n'apparait dans le
    texte, auquel cas le formulaire retombe sur une question explicite
    (utter_ask_category), elle-meme reformulee en langage naturel plutot
    qu'en noms de service bruts.
    """
    return best_keyword_match(normalized_text, CATEGORY_KEYWORDS, None)


# Signaux lexicaux d'urgence (retour utilisateur, 2026-07 : demander
# explicitement "quel est le niveau d'urgence ?" n'a pas de sens pour un
# utilisateur -- ce jugement doit se deduire de ce qu'il decrit, pas lui etre
# delegue). Meme esprit que CATEGORY_KEYWORDS/_infer_category_from_description
# ci-dessus, mais _infer_urgency_from_description ne retourne jamais None : au
# pire "medium", deja le repli neutre utilise partout ailleurs (voir
# ActionGenerateReclamationSummary, ActionCreateTicket) quand le slot est vide.
URGENCY_HIGH_KEYWORDS: List[Text] = [
    "urgent", "urgence", "immédiat", "immediat", "immédiatement", "immediatement",
    "bloqué", "bloque", "piraté", "pirate", "hacké", "hacke", "compromis",
    "volé", "vole", "arnaque", "arnaqué", "escroqu", "grave",
    "critique", "suspendu", "suspension",
]
URGENCY_LOW_KEYWORDS: List[Text] = [
    "pas urgent", "pas grave", "pas pressé", "pas presse", "quand vous pourrez",
    "quand vous pouvez", "a l'occasion", "à l'occasion", "juste une question",
    "juste pour savoir", "petite question",
]
# "depuis 5 jours"/"depuis 2 semaines" : un probleme qui traine depuis un
# moment est traite comme urgent (delai deja anormal), pas seulement les mots
# d'urgence explicites ci-dessus.
_ELAPSED_TIME_PATTERN = re.compile(r"\bdepuis\s+(\d+)\s*(jour|jours|semaine|semaines|mois)\b")


def _contains_keyword(text: Text, keywords: List[Text]) -> bool:
    # Frontieres de mot explicites (\b...\b), meme precaution que
    # best_keyword_match ci-dessus : un simple `kw in text` ferait par
    # exemple matcher "vole" dans "je voLE Rai" ou "grave" dans un mot plus
    # long, comme le cas "chat" dans "achat" deja documente sur ce fichier.
    return any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in keywords)


def _infer_urgency_from_description(normalized_text: Text) -> Text:
    """Deduit automatiquement le niveau d'urgence (low/medium/high) depuis la
    description libre du probleme -- jamais demande a l'utilisateur (voir
    validate_description ci-dessous, appele systematiquement des que la
    description est validee, remplace l'ancienne question utter_ask_urgency).
    """
    if _contains_keyword(normalized_text, URGENCY_HIGH_KEYWORDS):
        return "high"
    elapsed = _ELAPSED_TIME_PATTERN.search(normalized_text)
    if elapsed:
        amount, unit = int(elapsed.group(1)), elapsed.group(2)
        if unit.startswith("semaine") or unit.startswith("mois") or amount >= 3:
            return "high"
    if _contains_keyword(normalized_text, URGENCY_LOW_KEYWORDS):
        return "low"
    return "medium"


class ActionStartReclamation(Action):
    # Remplace l'utterance directe utter_reclamation_start declenchee comme
    # action : TEDPolicy rejouait cette derniere (confidence ~0.75) juste apres
    # action_create_ticket, sans nouveau message utilisateur, ce qui relancait
    # tout le formulaire (bug constate en pratique, cf. tracker inspection).
    # Une precondition explicite sur l'intention courante rend ce declenchement
    # invalide independamment de la politique Core qui a mene ici.
    def name(self) -> Text:
        return "action_start_reclamation"

    def run(self, dispatcher, tracker, domain):
        intent = (tracker.latest_message or {}).get("intent", {}).get("name")
        if intent != "create_reclamation":
            return []
        dispatcher.utter_message(response="utter_reclamation_start")

        # Question FAQ residuelle (audit "robustesse comportementale", cas
        # 10 : "Je veux porter plainte. Au fait c'est quoi le KYC ?") --
        # meme mecanisme que cote diagnostic (voir ActionRunDiagnosticStep),
        # complement silencieux si le service FAQ ne trouve rien.
        raw_text = tracker.latest_message.get("text") or ""
        trailing_question = _extract_trailing_faq_question(raw_text)
        if trailing_question:
            faq_answer = _search_faq(trailing_question)
            if faq_answer:
                dispatcher.utter_message(text=f"Au fait, à propos de « {trailing_question} » : {faq_answer}")

        return []


class ActionExtractReclamationEntities(Action):

    def name(self) -> Text:
        return "action_extract_reclamation_entities"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        description = tracker.get_slot("description") or ""
        category = tracker.get_slot("category") or self._infer_category(description)
        text = description.lower()

        entities = {
            # category (pas un rescan de la description) : audit -- rescanner
            # la description avec best_keyword_match(text, CATEGORY_KEYWORDS,
            # ...) pouvait renvoyer une categorie DIFFERENTE de celle deja
            # choisie et validee par l'utilisateur si la description contient
            # plus de mots-cles d'une autre categorie (ex. categorie=KYC mais
            # description evoquant "wallet"/"retrait" -> affichait "Wallet").
            # Constate en pratique ; le ticket reste correct cote base (il lit
            # le slot category), mais le message affiche a l'utilisateur juste
            # avant la confirmation le contredisait.
            "service": category,
            "device": self._extract_device(text),
            "error_type": self._extract_error_type(text),
            "keywords": self._extract_keywords(text),
            # Cle d'idempotence lue par ActionCreateTicket : generee ici une
            # seule fois (pas dans ActionCreateTicket lui-meme) car cette
            # action n'est PAS rejouee entre deux tentatives de confirmation
            # (voir "Create ticket after explicit confirmation" dans
            # rules.yml, qui va direct de intent:affirm a action_create_ticket
            # sans repasser par ici) -- une nouvelle tentative apres echec
            # reutilise donc la meme cle plutot que d'en generer une autre a
            # chaque "oui", ce qui permettrait a un serveur de tickets
            # honorant cette cle d'eviter un doublon si la 1ere requete avait
            # en realite reussi malgre une reponse perdue en route.
            "idempotency_key": str(uuid.uuid4()),
        }

        # Formulations variees (pas de dispatcher.utter_message(text=f"...")
        # fige) : meme principe que greeting.py -- seul l'habillage change,
        # jamais le fait que la categorie identifiee est entities['service'].
        dispatcher.utter_message(
            text=pick(
                f"J'ai bien noté qu'il s'agit d'un problème {entities['service']}.",
                f"D'accord, je classe votre demande dans la catégorie {entities['service']}.",
                f"Compris, je traite cela comme un problème {entities['service']}.",
            )
        )
        return [
            {"event": "slot", "name": "category", "value": category},
            {"event": "slot", "name": "extracted_entities", "value": json.dumps(entities, ensure_ascii=False)},
        ]

    def _infer_category(self, description: Text) -> Text:
        return best_keyword_match(description.lower(), CATEGORY_KEYWORDS, "Chat")

    def _extract_device(self, text: Text) -> Text:
        return _best_semantic_match("device", text, DEVICE_KEYWORDS, "inconnu")

    def _extract_error_type(self, text: Text) -> Text:
        return _best_semantic_match("error_type", text, ERROR_TYPE_KEYWORDS, "inconnu")

    def _extract_keywords(self, text: Text) -> List[Text]:
        keywords = [token for token in text.split() if len(token) > 3]
        return keywords[:8]


class ActionGenerateReclamationSummary(Action):

    def name(self) -> Text:
        return "action_generate_reclamation_summary"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        category = tracker.get_slot("category") or "inconnu"
        description = tracker.get_slot("description") or ""
        urgency = tracker.get_slot("urgency") or "medium"
        incident_date = tracker.get_slot("incident_date") or "non précisée"
        extracted_entities = tracker.get_slot("extracted_entities") or "{}"

        parsed_entities = json.loads(extracted_entities) if isinstance(extracted_entities, str) else extracted_entities
        service = parsed_entities.get("service", category)
        device = parsed_entities.get("device", "inconnu")
        error_type = parsed_entities.get("error_type", "inconnu")

        # device/error_type restent des metadonnees best-effort (voir
        # ActionExtractReclamationEntities) : jamais forcees dans un gabarit
        # de phrase du type "Le {error_type} est decrit comme suit" -- ce
        # gabarit suppose a tort un nom masculin singulier, alors que
        # "bloqué"/"non fonctionnel" (voir ERROR_TYPE_KEYWORDS) sont des
        # adjectifs : la phrase etait grammaticalement cassee des que le
        # champ etait identifie, pas seulement pour "inconnu" (repere en
        # test conversationnel, 505 tours, 2026-07-18 : "Le inconnu est
        # décrit comme suit" dans la quasi-totalite des cas reels). Affichees
        # seulement en complement, entre parentheses, quand reellement connues.
        extras = [part for part in (error_type, f"sur {device}" if device != "inconnu" else None) if part and part != "inconnu"]
        extras_text = f" ({', '.join(extras)})" if extras else ""

        priority_label = {"low": "faible", "medium": "moyenne", "high": "élevée"}.get(urgency, urgency)
        summary = (
            f"{pick('Pour récapituler', 'Voici ce que j’ai noté', 'Je résume votre demande')} : "
            f"un problème « {service} »{extras_text}, priorité {priority_label}, signalé pour le {incident_date}.\n"
            f"Description : {description}"
        )

        dispatcher.utter_message(text=summary)
        return [{"event": "slot", "name": "summary", "value": summary}]


class ValidateReclamationForm(FormValidationAction):

    def name(self) -> Text:
        return "validate_reclamation_form"

    async def required_slots(
        self,
        domain_slots: List[Text],
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Text]:
        # Bascule "modifier ou annuler ?" (voir action_ask_cancel_clarification
        # / validate_cancel_choice) : verifiee EN PREMIER, avant editing_field,
        # car les deux peuvent theoriquement s'enchainer (choisir "modifier",
        # puis refuser encore la confirmation plus tard).
        if tracker.get_slot("awaiting_cancel_choice"):
            return ["cancel_choice"]
        # Bascule de la reprise "modifier un champ" (voir validate_cancel_choice
        # / validate_field_to_edit) : tant que editing_field est actif, le
        # formulaire ne redemande QUE field_to_edit au lieu des 4 champs
        # habituels -- une fois le champ cible identifie et remis a None par
        # validate_field_to_edit, editing_field repasse a False et le
        # formulaire revient a la liste normale, qui ne redemande plus que ce
        # champ precis (les 3 autres restent deja remplis).
        if tracker.get_slot("editing_field"):
            return ["field_to_edit"]
        # cancel_choice/field_to_edit doivent figurer dans
        # reclamation_form.required_slots (domain.yml) pour que Rasa valide
        # leur mapping from_text conditionne a ce formulaire (voir le
        # commentaire sur required_slots dans domain.yml) -- mais ils ne
        # doivent JAMAIS etre demandes hors de leurs sous-etapes respectives
        # ci-dessus, d'ou ce filtrage explicite.
        return [slot for slot in domain_slots if slot not in ("cancel_choice", "field_to_edit")]

    def validate_cancel_choice(
        self,
        slot_value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        if isinstance(slot_value, str) and slot_value.strip():
            choice = best_keyword_match(slot_value.strip().lower(), CANCEL_CHOICE_KEYWORDS, "")
            if choice == "edit":
                # category/description/urgency/incident_date restent tous
                # remplis : required_slots() bascule vers ["field_to_edit"]
                # (editing_field) juste apres, sans redemander le reste.
                return {"cancel_choice": None, "awaiting_cancel_choice": False, "editing_field": True}
            if choice == "cancel":
                # Ne touche PAS category/description/urgency/incident_date ici
                # (contrairement a action_cancel_reclamation) : required_slots()
                # les voit tous deja remplis juste apres, donc le formulaire se
                # termine naturellement (active_loop -> null) sans rien
                # redemander. cancel_confirmed est le signal lu par la regle
                # "Cancel reclamation after clarification via form" (rules.yml)
                # pour declencher l'annulation reelle (message + reset complet)
                # une fois le formulaire desactive.
                return {"cancel_choice": None, "awaiting_cancel_choice": False, "cancel_confirmed": True}

        dispatcher.utter_message(response="utter_wrong_cancel_choice")
        return {"cancel_choice": None}

    def validate_field_to_edit(
        self,
        slot_value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        if isinstance(slot_value, str) and slot_value.strip():
            target_slot = best_keyword_match(slot_value.strip().lower(), FIELD_TO_EDIT_KEYWORDS, "")
            if target_slot:
                # Remet a None le slot vise plutot que de renvoyer un libelle :
                # le prochain passage de required_slots() (editing_field
                # redevenu False ici) redemande ce champ via son propre
                # utter_ask_<slot>, sans dupliquer sa logique de validation.
                return {
                    "field_to_edit": None,
                    "editing_field": False,
                    target_slot: None,
                }

        dispatcher.utter_message(response="utter_wrong_field_to_edit")
        return {"field_to_edit": None}

    def validate_category(
        self,
        slot_value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        # Depuis l'ajout de la deduction automatique dans validate_description
        # ci-dessous, cette question n'est plus posee que lorsque cette
        # deduction a echoue (aucun mot-cle de CATEGORY_KEYWORDS reconnu) ou
        # lors d'une modification explicite ("modifier" -> "categorie") --
        # continue donc d'accepter les codes bruts (ALLOWED_CATEGORIES) ET
        # leurs synonymes francais courants ("portefeuille", "connexion"...),
        # deja utilises pour la reformulation en langage naturel de
        # utter_ask_category/utter_wrong_category (domain.yml).
        #
        # Rasa peut re-valider un slot deja rempli (ex. reactivation du
        # formulaire) avec sa valeur actuelle, qui peut etre None : sans ce
        # garde, slot_value.strip() plantait l'action server (crash constate
        # en pratique : "'NoneType' object has no attribute 'strip'").
        if isinstance(slot_value, str):
            category = ALLOWED_CATEGORIES.get(slot_value.strip().lower())
            if category:
                return {"category": category}

        dispatcher.utter_message(response="utter_wrong_category")
        return {"category": None}

    def validate_description(
        self,
        slot_value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        if not isinstance(slot_value, str) or not slot_value.strip():
            dispatcher.utter_message(response="utter_wrong_description")
            return {"description": None}

        normalized = slot_value.strip().lower()
        generic_phrases = {
            "j'ai un problème",
            "j ai un problème",
            "j'ai un souci",
            "j ai un souci",
            "un problème",
            "un souci",
            "ça ne marche pas",
            "ca ne marche pas",
            "impossible",
            "ne fonctionne pas",
            "je n'arrive pas",
            "je n arrive pas",
        }

        if len(normalized) < 20 or any(phrase in normalized for phrase in generic_phrases):
            # Message distinct de la chaine reellement vide ci-dessus (voir
            # utter_description_too_short, domain.yml) : "mon solde est faux"
            # (18 caracteres) n'est pas vide, juste trop court/vague pour ce
            # plancher -- lui dire que sa description "ne peut pas etre vide"
            # ne veut rien dire pour lui. Trouve par test conversationnel
            # (505 tours, 2026-07-18) : ce cas precis bloquait la conversation
            # (l'utilisateur ne comprenant pas ce qu'on lui reproche).
            dispatcher.utter_message(response="utter_description_too_short")
            return {"description": None}

        stripped = slot_value.strip()
        if len(stripped) > MAX_DESCRIPTION_LENGTH:
            # Tronque plutot que de rejeter (audit "robustesse comportementale",
            # cas 38/39) : un utilisateur qui colle un pave de texte (SMS,
            # email, capture convertie...) a fait l'effort de tout fournir,
            # le renvoyer au point de depart serait punitif pour rien. Le
            # plafond protege contre l'epuisement de ressources (aucune
            # limite haute n'existait avant ce fix, seulement un plancher de
            # 20 caracteres) sans bloquer un cas d'usage legitime.
            stripped = stripped[:MAX_DESCRIPTION_LENGTH]
            dispatcher.utter_message(
                text=f"Votre description était longue, je l'ai raccourcie aux {MAX_DESCRIPTION_LENGTH} premiers caractères."
            )

        result: Dict[Text, Any] = {"description": stripped}

        # Deduit la categorie ICI, depuis ce que l'utilisateur vient de
        # decrire dans ses propres mots, plutot que de forcer juste apres une
        # question separee "quel est le service concerne (KYC/Wallet/Video/
        # Auth/Chat/Safety) ?" -- retour utilisateur (2026-07) : ce jargon
        # d'architecture interne n'aide pas un public qui ne maitrise pas la
        # plateforme. `description` est desormais demande AVANT `category`
        # (voir l'ordre de reclamation_form.required_slots, domain.yml) pour
        # que cette deduction ait une chance de s'appliquer -- si elle
        # reussit, required_slots() constate que category est deja rempli et
        # ne la redemande jamais. `not tracker.get_slot("category")` : ne
        # jamais ecraser une categorie deja fixee autrement (bouton, entite
        # extraite du message declencheur, ou reprise apres "modifier" ->
        # "categorie" specifiquement).
        if not tracker.get_slot("category"):
            inferred = _infer_category_from_description(normalized)
            if inferred:
                result["category"] = inferred

        # Urgence deduite automatiquement ici, jamais demandee a l'utilisateur
        # (retour utilisateur, 2026-07 -- voir _infer_urgency_from_description
        # ci-dessus). Toujours ecrasee avec la derniere description en date :
        # contrairement a category, il n'existe aucune autre source legitime
        # (bouton, entite du message declencheur) pour ce slot.
        result["urgency"] = _infer_urgency_from_description(normalized)

        return result

    def validate_incident_date(
        self,
        slot_value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        # Repli sur le texte brut du tour (audit conversationnel 400 messages,
        # 2026-07) : le mapping from_entity du slot incident_date (domain.yml,
        # sans condition -- il s'applique donc aussi pendant ce formulaire, en
        # plus du mapping from_text ci-dessous) peut fournir une valeur
        # PARTIELLE quand le NLU extrait mal l'etendue de l'entite sur une
        # reponse COURTE tapee directement en reponse a utter_ask_incident_date
        # (constate en pratique : "la semaine derniere" tape seul -> entite
        # extraite "semaine" uniquement, slot_value ne contient plus que ce
        # fragment, rejete par _looks_like_a_date). Le meme entrainement
        # fonctionne bien quand la date est mentionnee au milieu d'une phrase
        # plus longue (son contexte d'entrainement habituel, voir nlu.yml) --
        # seule la reponse courte et isolee degrade l'extraction. Sans ce
        # repli, une date pourtant valide etait rejetee a tort parce que seul
        # un fragment sans rapport avait ete retenu, jamais le texte complet
        # reellement tape par l'utilisateur.
        candidate = slot_value if isinstance(slot_value, str) else None
        if not (candidate and _looks_like_a_date(candidate)):
            raw_text = (tracker.latest_message or {}).get("text")
            if isinstance(raw_text, str) and _looks_like_a_date(raw_text):
                candidate = raw_text

        # Plafond AVANT _looks_like_a_date (cas 38/39) : celui-ci matche par
        # sous-chaine ("hier" n'importe ou dans le texte), un pave de
        # plusieurs milliers de caracteres contenant incidemment "hier"
        # passerait donc la validation existante sans ce garde-fou de
        # longueur -- s'applique aussi au repli sur le texte brut ci-dessus,
        # pas seulement a la valeur mappee.
        if (
            isinstance(candidate, str)
            and candidate.strip()
            and len(candidate.strip()) <= MAX_INCIDENT_DATE_LENGTH
            and _looks_like_a_date(candidate)
        ):
            return {"incident_date": candidate.strip()}

        dispatcher.utter_message(response="utter_wrong_incident_date")
        return {"incident_date": None}


class ActionRequestReclamationConfirmation(Action):

    def name(self) -> Text:
        return "action_request_reclamation_confirmation"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(response="utter_ask_confirmation")
        return [{"event": "slot", "name": "claim_requested", "value": True}]


class ActionCreateTicket(Action):

    def name(self) -> Text:
        return "action_create_ticket"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        # Meme filet de securite que ActionRunDiagnosticStep (voir sa
        # docstring) : constate en pratique ici aussi, TEDPolicy rejouait
        # cette action (ou une action de reprise du formulaire) juste apres
        # que RulePolicy l'ait deja executee a confiance 1.0, sans nouveau
        # message utilisateur entre les deux.
        if _already_ran_since_last_user_message(tracker, self.name()):
            return []

        if not tracker.get_slot("claim_requested"):
            # Audit ton/clarite : "Je dois d'abord confirmer..." se lisait
            # comme si c'etait le BOT qui devait confirmer, alors que c'est
            # une demande de confirmation adressee a l'utilisateur.
            dispatcher.utter_message(text="Confirmez d’abord la création de votre réclamation (oui/non) avant de continuer.")
            return []

        # Audit "robustesse comportementale", cas 40 : pour un ticket ne
        # d'une escalade de diagnostic (pas une reclamation classique via
        # formulaire), le probleme a pu se resoudre tout seul entre le
        # moment ou l'escalade a ete proposee et ce "oui" de confirmation
        # (ex. un retrait qui passe de pending a completed pendant que
        # l'utilisateur lit le message). escalation_recheck_context (voir
        # _respond_engine_outcome dans diagnostic.py) porte le strict
        # necessaire pour reinterroger le moteur une derniere fois avant de
        # creer un ticket devenu inutile.
        if tracker.get_slot("ticket_source") == "user_diagnostic_escalation":
            recheck_raw = tracker.get_slot("escalation_recheck_context")
            recheck_state = None
            if recheck_raw:
                try:
                    recheck_state = json.loads(recheck_raw) if isinstance(recheck_raw, str) else recheck_raw
                except (TypeError, ValueError):
                    recheck_state = None
            if recheck_state:
                recheck_result = _call_diagnostic_engine(tracker, recheck_state)
                if recheck_result and recheck_result.get("outcome") == "RESOLVED":
                    dispatcher.utter_message(
                        text=recheck_result.get(
                            "message",
                            "Bonne nouvelle : votre problème semble s'être résolu entre-temps, je n'ai pas créé de ticket.",
                        )
                    )
                    return [
                        {"event": "slot", "name": "claim_requested", "value": False},
                        {"event": "slot", "name": "ticket_source", "value": None},
                        {"event": "slot", "name": "escalation_recheck_context", "value": None},
                        {"event": "slot", "name": "category", "value": None},
                        {"event": "slot", "name": "description", "value": None},
                        {"event": "slot", "name": "urgency", "value": None},
                        {"event": "slot", "name": "incident_date", "value": None},
                        {"event": "slot", "name": "summary", "value": None},
                        {"event": "slot", "name": "extracted_entities", "value": None},
                    ]

        if not _ticket_rate_limiter.allow(tracker.sender_id):
            dispatcher.utter_message(
                text=(
                    "Vous avez déjà créé plusieurs réclamations récemment. "
                    "Merci de patienter un peu avant d'en soumettre une nouvelle."
                )
            )
            return []

        raw_entities = tracker.get_slot("extracted_entities") or "{}"
        try:
            parsed_entities = json.loads(raw_entities) if isinstance(raw_entities, str) else raw_entities
        except (TypeError, ValueError):
            parsed_entities = {}
        idempotency_key = parsed_entities.get("idempotency_key") or str(uuid.uuid4())

        # Disjoncteur ouvert (plusieurs echecs consecutifs recents) : on
        # n'attend pas encore un timeout de 10s pour rien, et les donnees de
        # l'utilisateur restent intactes (aucun evenement slot retourne ici)
        # pour permettre un nouvel essai plus tard sans tout ressaisir.
        if _ticket_circuit_breaker.is_open():
            logger.warning(
                "Disjoncteur de tickets ouvert : creation refusee sans tentative reseau (session=%s)",
                tracker.sender_id,
            )
            dispatcher.utter_message(
                text=(
                    "Ce service semble indisponible actuellement. "
                    "Vos informations sont conservées : répondez « oui » dans quelques instants pour réessayer."
                )
            )
            return []

        description = tracker.get_slot("description") or tracker.latest_message.get("text") or ""
        summary = tracker.get_slot("summary") or ""
        if _looks_like_threat(description) or _looks_like_threat(summary):
            # Audit "robustesse comportementale", cas 23 : pas de routage
            # special (create_reclamation capte deja correctement une
            # menace), juste un signal visible pour l'agent humain qui
            # reprendra ce ticket, avant meme d'ouvrir la description.
            description = "[Ton signalé : menace de plainte/signalement exprimée par l'utilisateur] " + description

        payload = {
            "category": tracker.get_slot("category") or "Unknown",
            "description": description,
            "urgency": tracker.get_slot("urgency") or "medium",
            "incident_date": tracker.get_slot("incident_date"),
            "summary": summary,
            "confirmation": "oui",
            "user_id": tracker.sender_id,
            # Tracabilite (voir domain.yml, slot ticket_source) : distingue
            # une reclamation classique (formulaire, valeur absente) d'un
            # ticket ne d'une escalade de diagnostic confirmee par l'utilisateur.
            "created_by": tracker.get_slot("ticket_source") or "user_reclamation_form",
            # Generee cote client (voir ActionExtractReclamationEntities) et
            # deduplique desormais cote serveur aussi (migrations/0009 +
            # complaints/service.py::create_ticket, audit robustesse) : une
            # relance apres un commit reussi mais reponse perdue (timeout
            # juste apres ce requests.post, par ex.) renvoie le ticket deja
            # cree au lieu d'en generer un second.
            "idempotency_key": idempotency_key,
        }

        try:
            response = request_with_retry("POST", TICKET_SERVICE_URL, json=payload, timeout=10)
            ticket = response.json()
            ticket_id = ticket.get("ticket_id")
            status = ticket.get("status")
            if not ticket_id or not status:
                # Reponse HTTP 200 mais forme inattendue : avant, ticket_id/
                # status manquants affichaient silencieusement "None" a
                # l'utilisateur comme si tout s'etait bien passe. Traite
                # desormais comme un echec (meme chemin que RequestException).
                raise ValueError(f"reponse de {TICKET_SERVICE_URL} sans ticket_id/status exploitable : {ticket!r}")
        except requests.HTTPError as error:
            # Audit robustesse : un 4xx (ex. payload malforme cote action
            # server) est un bug DE CE COTE, pas une preuve que le service de
            # tickets est en panne -- l'assimiler a une vraie panne reseau
            # ouvrait le disjoncteur pour TOUS les utilisateurs a cause d'un
            # seul payload invalide. Seul un 5xx (le service repond mais
            # signale sa propre defaillance), ou l'absence de reponse
            # exploitable, alimente le disjoncteur -- au meme titre qu'une
            # RequestException reseau ci-dessous.
            status_code = error.response.status_code if error.response is not None else None
            if status_code is None or status_code >= 500:
                _ticket_circuit_breaker.record_failure()
            logger.warning(
                "Echec de creation de ticket (HTTP %s) session=%s : %s", status_code, tracker.sender_id, error
            )
            dispatcher.utter_message(
                text=(
                    "Désolé, la création du ticket a échoué : le service est momentanément indisponible. "
                    "Vos informations sont conservées, répondez « oui » pour réessayer."
                )
            )
            return []
        except (requests.RequestException, ValueError) as error:
            logger.warning("Echec de creation de ticket session=%s : %s", tracker.sender_id, error)
            _ticket_circuit_breaker.record_failure()
            dispatcher.utter_message(
                text=(
                    "Désolé, la création du ticket a échoué : le service est momentanément indisponible. "
                    "Vos informations sont conservées, répondez « oui » pour réessayer."
                )
            )
            # Aucun evenement slot retourne ici (contrairement au succes
            # ci-dessous) : claim_requested reste True et tous les champs du
            # formulaire restent remplis. L'utilisateur peut donc reconfirmer
            # ("oui") pour reessayer sans tout ressaisir -- avant ce
            # correctif, ces 8 slots etaient reinitialises inconditionnellement
            # meme en cas d'echec, perdant toute la saisie sans recours.
            return []

        _ticket_circuit_breaker.record_success()
        _ticket_rate_limiter.record(tracker.sender_id)
        # Audit ton/clarite : ce message etait unique, sans variante, et
        # affichait le statut backend brut ("OPEN") en anglais -- alors que
        # utter_reclamation_confirmed (domain.yml), pense specifiquement pour
        # ce moment avec un ton plus chaleureux, n'etait en realite jamais
        # utilise. Remplace ce dernier plutot que de le router dynamiquement
        # (meme pattern deja etabli ici pour ActionStoreSuggestion/
        # ActionAcknowledgeComplaint : pick() avec la reference inline,
        # jamais un response= statique sans placeholder).
        status_label = TICKET_STATUS_LABELS.get(status, status)
        dispatcher.utter_message(
            text=pick(
                f"Merci, votre réclamation est bien enregistrée et en cours de traitement (numéro de ticket : {ticket_id}, statut : {status_label}).",
                f"C'est noté ! Votre réclamation a été créée avec succès (numéro de ticket : {ticket_id}, statut : {status_label}).",
                f"Votre réclamation est bien prise en compte (numéro de ticket : {ticket_id}, statut : {status_label}).",
            ),
            # Relance rapide (experience conversationnelle, 2026-07) : le
            # formulaire vient de se terminer, aucun autre flux n'est en
            # attente a ce point -- moment naturel pour reproposer les
            # actions rapides plutot que de laisser la conversation en
            # suspens.
            buttons=QUICK_ACTION_BUTTONS,
        )

        # Reinitialise aussi les champs du formulaire (pas seulement
        # claim_requested/ticket_source) : sans ca, l'etat de dialogue apres
        # creation du ticket ressemble encore a "formulaire de reclamation
        # deja rempli", ce qui poussait TEDPolicy a rejouer utter_reclamation_start
        # puis tout le formulaire juste apres, sans nouveau message utilisateur
        # (meme famille de bug que celui documente sur ActionRunDiagnosticStep).
        # Le vrai correctif de ce bug est dans data/rules.yml (la regle
        # declare desormais explicitement ce changement d'etat) : voir son
        # commentaire pour le detail du mecanisme.
        return [
            {"event": "slot", "name": "claim_requested", "value": False},
            {"event": "slot", "name": "ticket_source", "value": None},
            {"event": "slot", "name": "escalation_recheck_context", "value": None},
            {"event": "slot", "name": "category", "value": None},
            {"event": "slot", "name": "description", "value": None},
            {"event": "slot", "name": "urgency", "value": None},
            {"event": "slot", "name": "incident_date", "value": None},
            {"event": "slot", "name": "summary", "value": None},
            {"event": "slot", "name": "extracted_entities", "value": None},
        ]


class ActionCancelReclamation(Action):
    # Historique : remplace l'appel direct a utter_reclamation_cancelled qui
    # existait dans rules.yml -- une utterance seule n'emet aucun evenement
    # SlotSet, donc un "slot_was_set: claim_requested: false" declare comme
    # pas de regle sans action dediee ne se produisait jamais reellement
    # (confirme en pratique : claim_requested restait a True apres une
    # annulation). Consequence constatee : un "oui" totalement hors contexte,
    # dit plus tard dans la conversation, faisait matcher "Create ticket
    # after explicit confirmation" et creait un ticket avec les donnees
    # perimees de la reclamation pourtant annulee -- les autres slots du
    # formulaire n'etaient eux non plus jamais reinitialises.
    # Desormais declenchee uniquement quand validate_cancel_choice a resolu
    # "annuler" (voir "Cancel reclamation after clarification via form" dans
    # rules.yml) : reinitialise les memes slots que ActionCreateTicket, plus
    # awaiting_cancel_choice/cancel_confirmed/cancel_choice/editing_field/
    # field_to_edit (etat propre a la clarification modifier/annuler), par
    # symetrie -- annuler doit remettre le flux dans le meme etat "propre"
    # qu'une creation reussie.
    def name(self) -> Text:
        return "action_cancel_reclamation"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        # buttons= merge avec le texte tire au hasard par le response= (voir
        # domain.yml, utter_reclamation_cancelled) : pas de nouveau message,
        # juste des raccourcis concrets sur la relance deja presente dans ce
        # texte ("je peux continuer a vous aider...").
        dispatcher.utter_message(response="utter_reclamation_cancelled", buttons=QUICK_ACTION_BUTTONS)
        return [
            {"event": "slot", "name": "claim_requested", "value": False},
            {"event": "slot", "name": "awaiting_cancel_choice", "value": False},
            {"event": "slot", "name": "cancel_confirmed", "value": False},
            {"event": "slot", "name": "cancel_choice", "value": None},
            {"event": "slot", "name": "editing_field", "value": False},
            {"event": "slot", "name": "field_to_edit", "value": None},
            {"event": "slot", "name": "ticket_source", "value": None},
            {"event": "slot", "name": "escalation_recheck_context", "value": None},
            {"event": "slot", "name": "category", "value": None},
            {"event": "slot", "name": "description", "value": None},
            {"event": "slot", "name": "urgency", "value": None},
            {"event": "slot", "name": "incident_date", "value": None},
            {"event": "slot", "name": "summary", "value": None},
            {"event": "slot", "name": "extracted_entities", "value": None},
        ]


class ActionAskCancelClarification(Action):
    # Remplace l'ancien enchainement direct "deny -> action_cancel_reclamation" :
    # un "non" a la confirmation ne dit pas si l'utilisateur veut tout
    # abandonner ou juste corriger un champ. Ne dispatche volontairement
    # aucun message : la reactivation de reclamation_form juste apres (voir
    # rules.yml) fait poser utter_ask_cancel_choice automatiquement via
    # required_slots() = ["cancel_choice"] (ValidateReclamationForm), qui
    # capture la reponse en from_text (intent-agnostique) plutot que via une
    # intention NLU dediee -- voir le commentaire sur CANCEL_CHOICE_KEYWORDS
    # pour l'incident que l'approche par intention avait cause (deny lui-meme
    # devenait mal classe).
    def name(self) -> Text:
        return "action_ask_cancel_clarification"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        return [
            {"event": "slot", "name": "claim_requested", "value": False},
            {"event": "slot", "name": "awaiting_cancel_choice", "value": True},
        ]


# "toutes"/"liste"/... : l'utilisateur demande explicitement l'ensemble de ses
# reclamations plutot que la derniere seule (comportement par defaut de
# ActionConsultComplaints ci-dessous).
ALL_COMPLAINTS_KEYWORDS = ["toutes", "liste", "affiche", "montre"]

# "en cours" = pas encore cloturee/resolue -- pas un statut backend unique
# (ALLOWED_STATUSES = OPEN/IN_PROGRESS/RESOLVED/CLOSED, complaints/schemas.py) :
# filtre cote client sur cet ensemble plutot que de forcer une egalite sur un
# seul statut backend.
IN_PROGRESS_STATUSES = {"OPEN", "IN_PROGRESS"}
IN_PROGRESS_KEYWORDS = [
    "en cours", "pas encore résolu", "pas encore resolu",
    "toujours pas résolu", "toujours pas resolu", "pas terminé", "pas termine",
]


def _looks_like_all_complaints_request(text: Text) -> bool:
    return any(keyword in text for keyword in ALL_COMPLAINTS_KEYWORDS)


def _looks_like_in_progress_request(text: Text) -> bool:
    return any(keyword in text for keyword in IN_PROGRESS_KEYWORDS)


def _format_complaint_line(complaint: Dict[Text, Any]) -> Text:
    status_label = TICKET_STATUS_LABELS.get(complaint.get("status"), complaint.get("status"))
    return f"{complaint.get('ticket_id')} ({complaint.get('category')}) : {status_label}"


def _format_complaint_list(complaints: List[Dict[Text, Any]]) -> Text:
    return "\n".join(f"- {_format_complaint_line(c)}" for c in complaints)


class ActionConsultComplaints(Action):
    # Consultation des reclamations deja creees (rapport utilisateur, point
    # "consultation des reclamations") : aucun intent/action n'existait pour
    # repondre a "ou en est ma reclamation ?" avant cet ajout. Le seul
    # endpoint backend disponible jusqu'ici (GET /complaints/{ticket_id})
    # exige de CONNAITRE le ticket_id, que l'utilisateur ne fournit jamais
    # dans ces formulations -- voir le nouvel endpoint GET /complaints/mine
    # (complaints/router.py), filtre par le header X-User-ID plutot que par
    # un ticket_id explicite.
    def name(self) -> Text:
        return "action_consult_complaints"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        text = (tracker.latest_message.get("text") or "").lower()

        try:
            response = request_with_retry(
                "GET", TICKET_LIST_SERVICE_URL, headers={"X-User-ID": tracker.sender_id}, timeout=10
            )
            complaints = response.json()
        except (requests.RequestException, ValueError) as error:
            logger.warning("Echec de consultation des reclamations session=%s : %s", tracker.sender_id, error)
            dispatcher.utter_message(
                text="Je n'arrive pas à récupérer vos réclamations pour le moment. Merci de réessayer dans quelques instants."
            )
            return []

        if not complaints:
            dispatcher.utter_message(text="Je ne trouve aucune réclamation associée à votre compte.")
            return []

        if _looks_like_all_complaints_request(text):
            dispatcher.utter_message(text="Voici vos réclamations :\n" + _format_complaint_list(complaints))
            return []

        if _looks_like_in_progress_request(text):
            in_progress = [c for c in complaints if c.get("status") in IN_PROGRESS_STATUSES]
            if not in_progress:
                dispatcher.utter_message(text="Vous n'avez aucune réclamation en cours actuellement.")
            else:
                dispatcher.utter_message(text="Voici vos réclamations en cours :\n" + _format_complaint_list(in_progress))
            return []

        # Recherche par sujet (ex. "la reclamation concernant mon retrait") :
        # meme mots-cles que le formulaire de reclamation (CATEGORY_KEYWORDS),
        # mais pour RESTREINDRE une liste deja recuperee plutot que pour
        # choisir une categorie a valider. Sans correspondance, `complaints`
        # reste inchange et le plus recent (ci-dessous) fait office de reponse
        # par defaut -- comportement attendu pour "où en est ma réclamation ?"
        # sans autre precision.
        matched_category = best_keyword_match(text, CATEGORY_KEYWORDS, "")
        if matched_category:
            topic_matches = [c for c in complaints if c.get("category") == matched_category]
            if topic_matches:
                complaints = topic_matches

        latest = complaints[0]
        status_label = TICKET_STATUS_LABELS.get(latest.get("status"), latest.get("status"))
        dispatcher.utter_message(
            text=(
                f"Votre réclamation {latest.get('ticket_id')} ({latest.get('category')}) "
                f"est actuellement {status_label}."
            )
        )
        return []
