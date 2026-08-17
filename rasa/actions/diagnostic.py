import copy
import json
import logging
import re
import threading
import time
from os import getenv
from typing import Any, Callable, Dict, List, Optional, Text

import requests
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

# Audit observabilite : aucun logger n'existait dans rasa/actions -- chaque
# echec reseau (embeddings, capacites, moteur de diagnostic, tracabilite
# best-effort) etait capture puis silencieusement avale, invisible cote
# exploitation jusqu'a ce qu'un utilisateur se plaigne. rasa_sdk configure
# deja la sortie standard pour ses propres logs (voir "rasa_sdk.executor" /
# "rasa_sdk.endpoint" dans les logs du conteneur actions) -- ce logger de
# module s'y ajoute simplement, meme convention que le reste de la
# plateforme (voir app.main cote FastAPI).
logger = logging.getLogger(__name__)

from .common import (
    FALLBACK_ESCALATION_THRESHOLD,
    QUICK_ACTION_BUTTONS,
    SimpleCircuitBreaker,
    _already_ran_since_last_user_message,
    _consecutive_fallback_count,
    _extract_trailing_faq_question,
    _human_support_message,
    _search_faq,
    _strip_greeting_preamble,
    is_superagent_mode,
    pick,
    request_with_retry,
)

DIAGNOSTIC_SERVICE_URL = getenv("DIAGNOSTIC_SERVICE_URL", "http://fastapi:8000/diagnostic/resolve")
DIAGNOSTIC_CAPABILITIES_URL = getenv("DIAGNOSTIC_CAPABILITIES_URL", "http://fastapi:8000/diagnostic/capabilities")
EMBEDDING_SERVICE_URL = getenv("EMBEDDING_SERVICE_URL", "http://fastapi:8000/embeddings/query")
EMBEDDING_BATCH_SERVICE_URL = getenv("EMBEDDING_BATCH_SERVICE_URL", "http://fastapi:8000/embeddings/query/batch")
# Voir docs/15-modele-donnees.md (audit.agent_actions) : ingestion generique
# des decisions autonomes non couvertes par un audit specifique a un
# domaine. Ce process (actions) n'a pas d'acces direct a la base -- seul
# FastAPI ecrit en SQL (meme principe que tout le reste de l'architecture,
# voir docs/02-architecture.md) -- d'ou cet appel HTTP plutot qu'une
# ecriture directe.
AGENT_ACTION_AUDIT_URL = getenv("AGENT_ACTION_AUDIT_URL", "http://fastapi:8000/audit/actions")

_capabilities_cache: List[Dict[Text, Any]] | None = None
_capabilities_cached_at: float = 0.0

# Audit qualite du code, cas #5 : sans ce verrou, plusieurs requetes
# concurrentes arrivant juste apres l'expiration du cache declenchaient
# chacune leur propre appel HTTP redondant vers FastAPI (meme reponse,
# recalculee/retransmise plusieurs fois pour rien) le temps que la premiere
# reponse revienne peupler le cache. Double-checked locking : le chemin
# rapide (cache encore valide) reste sans verrou, seul le refresh est
# serialise.
_capabilities_lock = threading.Lock()

# Audit robustesse : voir son usage dans _fetch_capabilities plus bas.
_capabilities_circuit_breaker = SimpleCircuitBreaker()

# Duree de vie du cache avant de retenter un appel a FastAPI : un nouveau
# service/probleme cote Engine est desormais vu au plus tard apres ce delai,
# sans attendre un redemarrage complet du process actions (limite documentee
# jusqu'ici, cf. Phase 5 de docs/diagnostic-roadmap.md).
CAPABILITIES_CACHE_TTL_SECONDS = 300

# Audit "robustesse comportementale", cas 38/39 : aucun plafond haut n'existait
# sur les champs libres sans pattern de format (_extract_field_answer) --
# surface d'epuisement de ressources triviale sur un formulaire qui peut
# boucler plusieurs tours.
MAX_FIELD_ANSWER_LENGTH = 2000

# En dessous de ce score, un candidat n'est pas retenu (voir _score_capabilities).
# Remonter cette valeur (ex. 2.0) exigerait plusieurs mots-cles distincts avant
# de reconnaitre un probleme, si l'usage reel montre trop de faux positifs sur
# un seul mot-cle isole.
MIN_CAPABILITY_CONFIDENCE = 1.0

# Ecart RELATIF (pas absolu) entre le 1er et le 2e candidat de
# _score_capabilities, en dessous duquel on considere le 1er candidat comme
# pas assez clairement en tete -- utilise a la fois pour verrouiller un
# NOUVEAU probleme (_has_single_clear_winner) et pour detecter un changement
# de sujet en cours de diagnostic (_looks_like_new_topic). Relatif plutot
# qu'absolu car _score_capabilities retourne des scores sur deux echelles non
# comparables selon le repli utilise : comptage entier de mots-cles
# (MIN_CAPABILITY_CONFIDENCE) ou similarite cosinus 0-1 (MIN_EMBEDDING_SIMILARITY)
# -- un seuil absolu unique n'aurait pas le meme sens sur les deux.
#
# CALIBRAGE (4 messages reels, 8 problemes au catalogue -- a affiner avec plus
# de volume) : ce modele produit des similarites tres resserrees entre TOUS
# les candidats (0.80-0.87 sur l'ensemble du catalogue), donc un ecart relatif
# de 20% (valable pour la detection de changement de sujet, ou l'on veut etre
# tres conservateur) est presque JAMAIS atteint ici et forcait une
# desambiguisation meme sur des cas sans ambiguite reelle (ex. "Verifie mon
# KYC", gagnant net a 3.63% d'ecart, redemandait quand meme de choisir).
# Observe :
#   "mon retrait est bloque"            -> 0.07% (gagnant FAUX, a rejeter)
#   "Pourquoi mon compte est suspendu ?" -> 1.41% (gagnant FAUX, a rejeter)
#   "Verifie mon KYC"                    -> 3.63% (gagnant CORRECT, a garder)
#   "j'ai envoye un cadeau..."           -> 6.31% (gagnant CORRECT, a garder)
# 2% separe proprement les 4 -- distinct de CLASSIFICATION_RELATIVE_MARGIN
# (verrouillage initial, ce seuil-ci) et TOPIC_SWITCH_RELATIVE_MARGIN
# (interrompre un diagnostic deja en cours, delibs plus stricte car le cout
# d'une fausse interruption est plus visible pour l'utilisateur).
CLASSIFICATION_RELATIVE_MARGIN = 0.02

# Reste a 20% : deliberement plus strict que CLASSIFICATION_RELATIVE_MARGIN
# ci-dessus, car interrompre un diagnostic deja en cours pour proposer un
# changement de sujet doit rester rare (faux positif tres visible pour
# l'utilisateur), alors que redemander de choisir au tout debut d'un
# diagnostic est un simple aller-retour supplementaire.
TOPIC_SWITCH_RELATIVE_MARGIN = 0.20


def _fetch_capabilities() -> List[Dict[Text, Any]] | None:
    # Cache avec expiration (voir CAPABILITIES_CACHE_TTL_SECONDS) plutot que
    # pour la duree de vie complete du process : un nouveau service/probleme
    # cote Engine est vu au prochain appel qui suit l'expiration, sans
    # redemarrage.
    #
    # None = echec reseau ET aucun cache disponible pour amortir la panne (a
    # distinguer d'une liste vide reelle, qui elle reste en cache normalement).
    # Un echec avec un cache existant, meme expire, retombe sur ce cache
    # perime plutot que de traiter la panne comme "aucune capacite" -- eviter
    # qu'une panne de quelques secondes casse le diagnostic pour tout le
    # monde alors qu'on a deja une reponse recente et probablement toujours
    # valide.
    global _capabilities_cache, _capabilities_cached_at

    def _cache_is_fresh() -> bool:
        return _capabilities_cache is not None and (time.time() - _capabilities_cached_at) < CAPABILITIES_CACHE_TTL_SECONDS

    if _cache_is_fresh():
        return _capabilities_cache
    with _capabilities_lock:
        # Un autre thread a peut-etre deja rafraichi le cache pendant qu'on
        # attendait le verrou -- reverifier evite un second appel HTTP inutile.
        if _cache_is_fresh():
            return _capabilities_cache
        # Disjoncteur (audit robustesse) : pendant une panne prolongee de
        # FastAPI, ce cache expire toutes les CAPABILITIES_CACHE_TTL_SECONDS
        # et chaque tour qui suit re-paie un timeout complet de 10s avant de
        # retomber sur le cache perime. Le disjoncteur court-circuite cet
        # appel des que la panne est averee (3 echecs consecutifs), le temps
        # du cooldown.
        if _capabilities_circuit_breaker.is_open():
            return _capabilities_cache
        try:
            response = request_with_retry("GET", DIAGNOSTIC_CAPABILITIES_URL, timeout=10)
            _capabilities_cache = response.json().get("problems", [])
            _capabilities_cached_at = time.time()
            _capabilities_circuit_breaker.record_success()
            return _capabilities_cache
        except requests.RequestException as exc:
            logger.warning("Echec de recuperation des capacites (%s) : %s", DIAGNOSTIC_CAPABILITIES_URL, exc)
            _capabilities_circuit_breaker.record_failure()
            return _capabilities_cache


# Couvre la negation generale francaise ("ne/n' ... pas/plus/jamais/rien/aucun",
# avec ou sans elision et jusqu'a quelques mots entre les deux), plus les
# tournures orales qui laissent tomber le "ne" ("pas besoin", "plus besoin").
NEGATION_PATTERN = re.compile(
    r"\b(?:ne|n['’])\b.{0,25}?\b(?:pas|plus|jamais|rien|aucun\w*|nul\w*)\b"
    r"|\b(?:pas|plus|aucun\w*)\s+(?:besoin|probl[eè]me|souci)\b",
    re.IGNORECASE,
)


def _keyword_present(keyword: Text, text: Text) -> bool:
    # Presence brute (mot entier), sans jugement de negation/resolution --
    # utilise par _filter_negated_or_resolved pour distinguer "ce mot-cle
    # n'apparait pas du tout" (rien a nier, le score semantique tranche seul)
    # de "il apparait mais est nie/resolu" (_keyword_matches ci-dessous).
    return re.search(rf"\b{re.escape(keyword.lower())}\b", text) is not None


def _keyword_matches(keyword: Text, text: Text) -> bool:
    # Correspondance sur mot(s) entier(s) plutot que sous-chaine brute (`in`) :
    # une sous-chaine peut matcher par coincidence a l'interieur d'un autre mot
    # sans rapport avec le sens du mot-cle.
    match = re.search(rf"\b{re.escape(keyword.lower())}\b", text)
    if match is None:
        return False
    # Ignore un mot-cle precede d'une negation a proximite immediate (ex. "je
    # n'ai plus de probleme avec mon retrait" ne doit pas faire gagner
    # "retrait" -- seule la fenetre juste avant le mot-cle est regardee, pas
    # tout le message, pour ne pas etre trop agressif sur des phrases longues
    # qui nient autre chose plus tot).
    #
    # Volontairement PAS elargi a une fenetre apres le mot-cle ni a
    # _looks_like_resolution ici (une version elargie a ete tentee puis
    # RETIRE apres mesure -- voir _keyword_resolved_or_negated ci-dessous,
    # utilisee uniquement par _filter_negated_or_resolved) : NEGATION_PATTERN
    # matche aussi bien "n'a jamais ete credite"/"n'a pas ete ajoutee"/"n'a
    # rien recu", des negations qui decrivent le MALFONCTIONNEMENT lui-meme
    # (exactement la plainte de l'utilisateur), que "n'est plus bloque" (la
    # resolution du probleme) -- utiliser cette fonction telle quelle comme
    # FILTRE (pas comme simple depart de tiebreak, son usage historique)
    # faisait perdre a tort topup_not_credited/gift_not_received/
    # withdrawal_pending sur des descriptions tres normales de ces problemes
    # (grande vague de tests conversationnels, 2e passage).
    preceding_window = text[max(0, match.start() - 40):match.start()]
    if NEGATION_PATTERN.search(preceding_window):
        return False
    return True


def _score_capabilities_keywords(text: Text, problems: List[Dict[Text, Any]]) -> List[Dict[Text, Any]]:
    # Repli historique (Phase avant embeddings) : matching par comptage de
    # mots-cles. Conserve comme filet de secours quand le service
    # d'embeddings est indisponible ou qu'aucun probleme n'a d'embedding
    # precalcule (voir _score_capabilities) -- pas seulement pour la
    # retro-compatibilite, une vraie panne de FastAPI ne doit pas rendre le
    # diagnostic totalement aveugle.
    scored = []
    for problem in problems:
        keywords = problem.get("keywords", [])
        if not keywords:
            continue
        matched = sum(1.0 for kw in keywords if _keyword_matches(kw, text))
        if matched < MIN_CAPABILITY_CONFIDENCE:
            continue
        fields = (
            problem.get("required_fields", [])
            + problem.get("optional_fields", [])
            + problem.get("fallback_fields", [])
        )
        scored.append(
            {
                "service_id": problem["service"],
                "problem_id": problem["id"],
                "label": problem["label"],
                "confidence": matched,
                # Ratio (mots-cles trouves / mots-cles definis) : sert
                # uniquement de departage entre deux problemes a egalite de
                # `confidence` brute, pour ne pas avantager structurellement
                # un probleme qui a beaucoup plus de mots-cles definis qu'un
                # autre.
                "match_ratio": matched / len(keywords),
                "required_fields": [f["name"] for f in problem.get("required_fields", [])],
                "optional_fields": [f["name"] for f in problem.get("optional_fields", [])],
                "fallback_fields": [f["name"] for f in problem.get("fallback_fields", [])],
                "field_specs": {f["name"]: f for f in fields},
            }
        )
    # Departage deterministe : confidence brute, puis ratio, puis label
    # alphabetique -- sans le dernier critere, l'ordre entre deux problemes
    # a egalite parfaite dependait de l'ordre d'iteration du dict Python
    # (non significatif).
    scored.sort(key=lambda item: (-item["confidence"], -item["match_ratio"], item["label"]))
    return scored


# En dessous de cette similarite cosinus, un candidat n'est pas retenu (voir
# _score_capabilities_embeddings).
#
# RECALIBRE (2026-07) suite au passage e5-small -> e5-base (voir
# app/shared/embeddings/service.py) : l'ancien seuil de 0.83, calibre sur
# e5-small avec un seul probleme de reference, laissait passer un taux de
# FAUX POSITIFS de 65% sur un corpus de 20 messages neutres (salutations,
# remerciements, questions hors-sujet) teste contre le catalogue reel a 8
# problemes (wallet+user) -- une simple salutation ("Bonsoir comment
# allez-vous ?") suffisait a declencher un probleme diagnostic au hasard.
# Mesure sur ce meme corpus avec e5-base, seuil balaye de 0.83 a 0.88 :
#   0.83 : FP=2/20 (10%)  TP=45/59 (76%)
#   0.84 : FP=0/20 (0%)   TP=45/59 (76%)  <- retenu, aucune perte de rappel
#   0.85 : FP=0/20 (0%)   TP=45/59 (76%)
#   0.86 : FP=0/20 (0%)   TP=38/59 (64%)  <- le rappel commence a chuter
#   0.87 : FP=0/20 (0%)   TP=30/59 (51%)
# 0.84 est le plus bas seuil qui elimine tous les faux positifs du corpus de
# test SANS sacrifier de rappel par rapport a 0.83 -- pas de compromis a
# faire ici, contrairement a e5-small.
#
# LIMITE INCHANGEE : ce corpus (20 negatifs, 59 positifs en leave-one-out sur
# les 8 problemes actuels) reste petit face a la diversite reelle des
# formulations utilisateur -- a recalibrer si l'usage reel montre trop de
# faux positifs/negatifs, ou si de nouveaux problemes/services rejoignent le
# catalogue. Le repli sur _score_capabilities_keywords (mots-cles) reste
# utile comme filet de securite partiel en cas de panne du service
# d'embeddings (n'aide pas si le message ne contient aucun mot-cle du
# manifeste non plus).
#
# VERIFIE (2026-07-30) apres le passage e5-base -> BGE-M3 (voir
# app/shared/embeddings/service.py) : sur des phrases completes
# representatives de TEST_MESSAGES (fastapi/tests/test_diagnostic_classification_quality.py),
# les scores restent largement au-dessus de 0.84 -- "je veux retirer de
# l'argent mais ça n'a jamais été crédité" -> 0.967, "j'ai fait une recharge
# mais mon solde n'a pas changé" -> 0.899, "ma vérification KYC est bloquée
# depuis des jours" -> 0.864, "je n'arrive plus à me connecter à mon compte,
# il semble bloqué" -> 0.985. BGE-M3 ne degrade la similarite que sur les
# messages COURTS (1-3 mots, voir le plancher de repechage ci-dessous).
#
# RECALIBRE (2026-07-30, fastapi/scripts/diagnostic_test_report.py, corpus de
# 72 requetes cible sur les collisions deja documentees dans les manifestes) :
# 0.84 n'introduisait aucun faux positif mais restait inutilement conservateur
# -- balayage de seuils sur ce corpus (POST /diagnostic/debug/classify) :
#   0.65 : FP=2/20  TP=52/52 (rappel 100%)
#   0.70 : FP=0/20  TP=51/52 (F1=0.990, meilleur de tout le balayage)
#   0.75 : FP=0/20  TP=51/52 (retenu, meme F1 que 0.70 avec une marge de securite)
#   0.80 : FP=0/20  TP=51/52
#   0.84 : FP=0/20  TP=44/52 (F1=0.917, ancien seuil -- ~15% de rappel perdu pour rien)
#   0.85 : FP=0/20  TP=43/52
# 0.75 domine strictement l'ancien 0.84 sur ce corpus (meme 0 faux positif,
# meilleur rappel) -- pas un compromis. LIMITE INCHANGEE (voir ci-dessus) :
# a revalider si l'usage reel montre des faux positifs que ce corpus n'a pas
# couverts.
MIN_EMBEDDING_SIMILARITY = 0.75

# Second plancher, UNIQUEMENT pour _rescue_unique_keyword_match plus bas -- ne
# remplace ni n'abaisse MIN_EMBEDDING_SIMILARITY (jamais touche globalement,
# voir calibration ci-dessus).
#
# RECALIBRE (2026-07-30) suite au passage e5-base -> BGE-M3 : contrairement a
# MIN_EMBEDDING_SIMILARITY (phrases completes, non affecte), les messages
# COURTS utilises ici degradent nettement avec BGE-M3. Mesure empirique
# (meme modele, meme corpus KYC que
# fastapi/tests/test_diagnostic_classification_quality.py::TestKeywordRescuePreconditions) :
# "kyc" -> 0.5966, "mon kyc" -> 0.5880, "kyc svp" -> 0.4621, "check kyc" ->
# 0.6467, "statut kyc" -> 0.4985 -- leur meilleur score (le bon probleme)
# tombe entre 0.46 et 0.65, largement sous l'ancien plancher de 0.78. Le
# probleme attendu reste NEANMOINS le mieux classe dans tous les cas (marge
# nette sur le 2e, voir le meme test) : ce n'est pas une perte de
# discrimination, seulement une baisse de l'echelle absolue des scores.
# 0.40 laisse une marge de securite sous le minimum observe (0.4621) sans
# se rapprocher du seuil normal -- a revalider si un futur message hors-sujet
# tres court est promu a tort (corpus negatif pas mesure pour ce plancher,
# contrairement a MIN_EMBEDDING_SIMILARITY ci-dessus).
KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY = 0.40


# Audit robustesse : contrairement au disjoncteur de tickets (reclamation.py),
# aucune protection n'existait ici alors que ces deux fonctions sont appelees
# a CHAQUE tour (potentiellement plusieurs fois : message entier + repli par
# clause + par segment, voir _score_capabilities) -- une panne prolongee du
# service d'embeddings faisait payer un timeout de 10s par appel, a repetition,
# plutot que d'echouer vite une fois la panne averee et de retomber
# immediatement sur le repli mots-cles.
_embeddings_circuit_breaker = SimpleCircuitBreaker()


def _embed_message(text: Text) -> List[float] | None:
    # Le modele d'embeddings (intfloat/multilingual-e5-small) tourne cote
    # FastAPI (voir app.shared.embeddings), pas ici : un seul exemplaire du
    # modele pour toute la plateforme plutot que de le recharger dans ce
    # process actions. None = panne reseau, gere par le repli sur
    # _score_capabilities_keywords (voir _score_capabilities).
    if _embeddings_circuit_breaker.is_open():
        return None
    try:
        response = request_with_retry("POST", EMBEDDING_SERVICE_URL, json={"text": text}, timeout=10)
        _embeddings_circuit_breaker.record_success()
        return response.json().get("embedding")
    except requests.RequestException as exc:
        logger.warning("Echec d'embedding (%s) : %s", EMBEDDING_SERVICE_URL, exc)
        _embeddings_circuit_breaker.record_failure()
        return None


def _embed_messages(texts: List[Text]) -> List[List[float]] | None:
    # Audit qualite du code, cas #4 : un seul aller-retour HTTP pour TOUTES
    # les clauses d'un message, plutot qu'un appel par clause (voir l'ancienne
    # boucle dans _score_capabilities_embeddings_by_clause) -- FastAPI encode
    # le lot en un seul forward pass modele (voir
    # app.shared.embeddings.embed_query_batch), ce qui est a la fois moins de
    # latence reseau cumulee ET plus efficace cote modele qu'un encode par
    # texte. None = panne reseau, gere par l'appelant comme
    # _embed_message (pas de rescue par clause dans ce cas, comme avant).
    if not texts:
        return []
    # Meme disjoncteur que _embed_message (partage : les deux appellent le
    # meme service d'embeddings cote FastAPI, une panne touche les deux
    # identiquement).
    if _embeddings_circuit_breaker.is_open():
        return None
    try:
        response = request_with_retry("POST", EMBEDDING_BATCH_SERVICE_URL, json={"texts": texts}, timeout=10)
        _embeddings_circuit_breaker.record_success()
        return response.json().get("embeddings")
    except requests.RequestException as exc:
        logger.warning("Echec d'embedding en lot (%s, %d textes) : %s", EMBEDDING_BATCH_SERVICE_URL, len(texts), exc)
        _embeddings_circuit_breaker.record_failure()
        return None


def _report_agent_action(
    *,
    session_id: Text,
    domain: Text,
    action_type: Text,
    input_data: Dict[Text, Any],
    output_data: Dict[Text, Any] | None = None,
) -> None:
    """Trace une decision autonome vers audit.agent_actions (voir
    docs/15-modele-donnees.md), best-effort et non-bloquant : appele en fin
    de traitement d'un tour (voir ActionRunDiagnosticStep.run()), jamais en
    amont d'une reponse utilisateur, pour qu'une panne reseau ou une erreur
    d'ecriture cote FastAPI ne retarde/casse jamais la conversation. Meme
    principe que _embed_message/_embed_messages ci-dessus : une exception
    reseau est avalee, pas de repli ni de retry (une trace manquante est
    sans consequence fonctionnelle, contrairement a une classification ou un
    embedding manquant)."""
    try:
        requests.post(
            AGENT_ACTION_AUDIT_URL,
            json={
                "session_id": session_id,
                "domain": domain,
                "action_type": action_type,
                "input_data": input_data,
                "output_data": output_data or {},
            },
            timeout=5,
        )
    except requests.RequestException as exc:
        # Best-effort, non-bloquant (voir docstring) : une trace manquante
        # reste sans consequence fonctionnelle, donc INFO plutot que WARNING
        # -- mais desormais visible plutot qu'entierement avalee (audit
        # observabilite), utile pour reperer une panne PROLONGEE de
        # AGENT_ACTION_AUDIT_URL qui viderait silencieusement audit.agent_actions.
        logger.info("Echec de tracabilite best-effort (%s) : %s", AGENT_ACTION_AUDIT_URL, exc)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    # Les deux vecteurs sont deja normalises cote FastAPI (voir
    # app.shared.embeddings.embed_query/embed_passage) : le produit scalaire
    # EST la similarite cosinus.
    return sum(x * y for x, y in zip(a, b))


def _best_similarity(message_embedding: List[float], problem: Dict[Text, Any]) -> float:
    # Meme calcul que dans _score_capabilities_embeddings (meilleur score
    # entre la description et toutes les example_phrases), mais SANS filtrer
    # sur MIN_EMBEDDING_SIMILARITY -- extrait pour etre reutilise par
    # _rescue_unique_keyword_match, qui doit justement examiner des scores
    # sous ce seuil.
    candidate_vectors = [problem["embedding"]] + list(problem.get("example_embeddings") or [])
    return max(_cosine_similarity(message_embedding, vector) for vector in candidate_vectors)


def _score_capabilities_embeddings(
    message_embedding: List[float], problems: List[Dict[Text, Any]]
) -> List[Dict[Text, Any]]:
    # Remplace le comptage de mots-cles par une similarite semantique : gere
    # les synonymes/reformulations qu'aucune liste de mots-cles ne peut
    # anticiper (ex. "mon argent n'est jamais arrive" pour un retrait
    # bloque). Ne considere que les problemes ayant un embedding precalcule
    # (voir CapabilityProblemSummary.embedding, calcule une seule fois par
    # rafraichissement du registre cote FastAPI, pas a chaque message).
    #
    # Audit "code mort et complexite" : une version vectorisee numpy (matrice
    # unique, un seul produit matriciel au lieu d'une boucle Python) a ete
    # tentee ici puis ABANDONNEE apres mesure -- voir benchmark ci-dessous.
    # `np.asarray()` reconstruit un tableau C a partir de listes Python a
    # CHAQUE appel (le catalogue n'est jamais mis en cache sous forme
    # numpy) : ce cout de conversion domine largement le gain du calcul
    # vectorise tant que le catalogue reste petit, rendant la version numpy
    # plus LENTE que la boucle Python simple ci-dessous a l'echelle actuelle :
    #   8 problemes   : Python 6.7ms  vs numpy 13.0ms  (numpy 2x plus lent)
    #   50 problemes  : Python 34.2ms vs numpy 59.5ms  (numpy 1.7x plus lent)
    #   200 problemes : Python 170.7ms vs numpy 110.6ms (numpy enfin 1.5x plus rapide)
    # Le catalogue reel compte aujourd'hui une poignee de problemes (voir
    # GET /diagnostic/capabilities) : la version vectorisee y serait une
    # regression pure, pas une optimisation. A REVISITER si le catalogue
    # grossit significativement (des dizaines de services) -- la bonne
    # version vectorisee devrait alors precalculer les tableaux numpy UNE
    # FOIS au rafraichissement du cache (_fetch_capabilities), pas a chaque
    # message, pour ne payer le cout de conversion qu'une fois toutes les
    # CAPABILITIES_CACHE_TTL_SECONDS plutot qu'a chaque tour de conversation.
    scored = []
    for problem in problems:
        embedding = problem.get("embedding")
        if not embedding:
            continue
        # Compare au MEILLEUR score parmi la description et toutes les
        # example_phrases (voir CapabilityProblemSummary.example_embeddings) :
        # une seule phrase de reference (souvent formelle) rate les messages
        # formules dans un style different -- constate en pratique (un
        # paraphrase legitime sans aucun mot-cle avait ete rejete a 0.827,
        # sous le seuil, avec la seule description formelle comme reference).
        similarity = _best_similarity(message_embedding, problem)
        if similarity < MIN_EMBEDDING_SIMILARITY:
            continue
        fields = (
            problem.get("required_fields", [])
            + problem.get("optional_fields", [])
            + problem.get("fallback_fields", [])
        )
        scored.append(
            {
                "service_id": problem["service"],
                "problem_id": problem["id"],
                "label": problem["label"],
                "confidence": similarity,
                # Pas de notion distincte de "ratio" pour un score de
                # similarite (deja normalise entre -1 et 1, contrairement a
                # un compte brut de mots-cles) : reutilise la meme valeur
                # pour le departage, coherent avec _score_capabilities_keywords.
                "match_ratio": similarity,
                "required_fields": [f["name"] for f in problem.get("required_fields", [])],
                "optional_fields": [f["name"] for f in problem.get("optional_fields", [])],
                "fallback_fields": [f["name"] for f in problem.get("fallback_fields", [])],
                "field_specs": {f["name"]: f for f in fields},
            }
        )
    scored.sort(key=lambda item: (-item["confidence"], -item["match_ratio"], item["label"]))
    return scored


def _keyword_signal(text: Text, keywords: List[Text]) -> float:
    return sum(1.0 for kw in keywords if _keyword_matches(kw, text))


def _apply_keyword_tiebreak(
    text: Text, scored: List[Dict[Text, Any]], problems: List[Dict[Text, Any]]
) -> List[Dict[Text, Any]]:
    # Repli hybride, PAS une pondération globale (voir _score_capabilities) :
    # les embeddings, sur une phrase courte, peuvent placer deux candidats a
    # quelques millismes l'un de l'autre alors que leurs mots-cles respectifs
    # ne se chevauchent pas du tout -- constate en pratique, ex. "mon retrait
    # est bloque" verrouillait a tort "Suppression de compte" (ecart embedding
    # 0.07%) alors que "retrait"/"bloque" sont des mots-cles EXCLUSIFS de
    # withdrawal_pending, absents des mots-cles des candidats concurrents.
    # N'intervient donc que quand les embeddings n'ont PAS deja un gagnant net
    # (voir _has_meaningful_margin) -- sur un cas déjà clair, ce repli ne
    # change jamais le resultat, aucun risque de regression sur les cas qui
    # marchaient deja.
    if not scored or _has_meaningful_margin(scored, CLASSIFICATION_RELATIVE_MARGIN):
        return scored

    keywords_by_key = {(p["service"], p["id"]): p.get("keywords", []) for p in problems}
    top_n = scored[:3]
    matched_indices = [
        i
        for i, candidate in enumerate(top_n)
        if _keyword_signal(text, keywords_by_key.get((candidate["service_id"], candidate["problem_id"]), []))
        >= MIN_CAPABILITY_CONFIDENCE
    ]
    # Departage seulement si un SEUL candidat parmi les mieux places a un
    # signal lexical decisif -- si aucun n'en a, ou si plusieurs se
    # disputent aussi les mots-cles, l'ambiguite est reelle : on la laisse
    # remonter telle quelle vers _mark_pending_choices (dernier recours de
    # CLASSIFICATION_RULES), qui demande explicitement a l'utilisateur de
    # trancher plutot que de deviner une 2e fois.
    if len(matched_indices) != 1:
        return scored

    winner_index = matched_indices[0]
    winner = dict(top_n[winner_index])
    rest = [candidate for i, candidate in enumerate(scored) if i != winner_index]
    # Le score d'embedding du gagnant lexical reste souvent proche des
    # autres (c'est justement pourquoi les embeddings seuls hesitaient) --
    # sans ajustement, un controle de marge ulterieur sur cette meme liste
    # (_has_single_clear_winner, rappele juste apres depuis
    # _run_classification_rules) la jugerait encore ambigue et annulerait ce
    # departage. On remonte sa confiance juste au-dessus du nouveau 2e pour
    # que la marge soit nette en aval.
    winner["confidence"] = rest[0]["confidence"] * (1 + CLASSIFICATION_RELATIVE_MARGIN + 0.01)
    return [winner] + rest


def _rescue_unique_keyword_match(
    text: Text,
    message_embedding: List[float] | None,
    problems_with_embeddings: List[Dict[Text, Any]],
) -> Dict[Text, Any] | None:
    """Dernier recours quand ni _score_capabilities_embeddings, ni le repli
    par clause, ni _apply_keyword_tiebreak ne retiennent AUCUN candidat.
    _apply_keyword_tiebreak ne fait que REORDONNER des candidats deja
    retenus (son garde `if not scored: return scored` l'empeche d'agir sur
    une liste vide) -- jamais en promouvoir un nouveau. Ce cas-ci comble ce
    trou precis : un mot-cle sans ambiguite (ex. "kyc") dont le SEUL
    probleme concerne du catalogue est passe sous MIN_EMBEDDING_SIMILARITY
    de peu (constate en pratique : "kyc", "mon kyc", "kyc svp" tombent entre
    0.80 et 0.835 alors que kyc_status_issue est deja leur meilleur score).

    Ne rescape QUE si :
      1) un SEUL probleme de TOUT le catalogue a un signal lexical decisif
         sur ce message precis (_keyword_signal >= MIN_CAPABILITY_CONFIDENCE,
         meme seuil que _apply_keyword_tiebreak) -- si plusieurs problemes
         partagent un mot-cle present dans ce message (ex. "bloque", partage
         par withdrawal_pending et account_access_blocked), l'ambiguite est
         reelle, aucune promotion ;
      2) le score embedding reel de ce probleme atteint au moins
         KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY -- un mot-cle isole dans un
         message par ailleurs hors-sujet ne doit pas suffire seul (un
         message sans aucun mot-cle du catalogue echoue de toute facon a la
         condition 1, avant meme d'atteindre ce plancher).

    Confidence = score REEL (pas gonfle comme _apply_keyword_tiebreak) : un
    candidat seul dans la liste est deja traite comme un gagnant net par
    _has_meaningful_margin (len(candidates) < 2 -> True), pas besoin
    d'artifice.
    """
    if message_embedding is None or not problems_with_embeddings:
        return None
    matches = [
        problem
        for problem in problems_with_embeddings
        if _keyword_signal(text, problem.get("keywords", [])) >= MIN_CAPABILITY_CONFIDENCE
    ]
    if len(matches) != 1:
        return None
    problem = matches[0]
    similarity = _best_similarity(message_embedding, problem)
    if similarity < KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY:
        return None
    fields = (
        problem.get("required_fields", [])
        + problem.get("optional_fields", [])
        + problem.get("fallback_fields", [])
    )
    return {
        "service_id": problem["service"],
        "problem_id": problem["id"],
        "label": problem["label"],
        "confidence": similarity,
        "match_ratio": similarity,
        "required_fields": [f["name"] for f in problem.get("required_fields", [])],
        "optional_fields": [f["name"] for f in problem.get("optional_fields", [])],
        "fallback_fields": [f["name"] for f in problem.get("fallback_fields", [])],
        "field_specs": {f["name"]: f for f in fields},
    }


# Negation d'ETAT, restreinte a une liste explicite d'adjectifs/participes
# NEGATIFS (bloque, suspendu, banni, refuse, rejete...) -- PAS "n'est plus/pas
# + n'importe quoi". "mon KYC n'est plus bloque" (resolution, bloque=etat
# negatif) et "ma recharge n'est pas creditee" (probleme toujours actif,
# creditee=resultat POSITIF attendu) ont exactement la MEME construction
# grammaticale (copule etre + plus/pas + participe passe) -- seule la
# polarite semantique du participe les distingue, une negation generique
# "n'est plus/pas X" ne peut pas les separer sans lexique. Constate en
# pratique (grande vague de tests conversationnels, 3e passage) : une
# premiere version sans cette liste filtrait a tort topup_not_credited sur
# "n'est pas creditee". Cette liste reprend les mots des `keywords` deja
# declares dans les manifestes concernes (voir wallet_stub/user_stub
# diagnostic/manifest.py) -- pas invente ici.
_NEGATIVE_STATE_WORDS = (
    "bloqu[ée]e?s?", "suspendu[e]?s?", "banni[e]?s?", "refus[ée]e?s?", "rejet[ée]e?s?",
)
_RESOLVED_STATE_PATTERN = re.compile(
    r"\bn['’]est\s+(?:plus|pas)\s+(?:" + "|".join(_NEGATIVE_STATE_WORDS) + r")\b"
    r"|\b(?:pas|plus|aucun\w*)\s+(?:besoin|probl[eè]me|souci)\b",
    re.IGNORECASE,
)


def _clause_containing(text: Text, position: int) -> Text:
    """Le segment de texte delimite par les connecteurs grammaticaux
    (_CLAUSE_CONNECTORS, memes que _clause_candidates plus bas) qui contient
    la position donnee -- une negation/resolution dans une AUTRE clause (ex.
    "j'ai fait une recharge MAIS mon solde n'a pas change") ne doit pas
    s'appliquer a un mot-cle d'une clause differente ("recharge")."""
    bounds = [0] + [m.end() for m in _CLAUSE_CONNECTORS.finditer(text)] + [len(text) + 1]
    for start, end in zip(bounds, bounds[1:]):
        if start <= position < end:
            return text[start:end]
    return text


def _keyword_resolved_or_negated(keyword: Text, text: Text) -> bool:
    """Version dediee a _filter_negated_or_resolved (distincte de
    _keyword_matches, utilisee elle pour le tiebreak/rescue) : cherche une
    negation d'ETAT (_RESOLVED_STATE_PATTERN) OU une phrase de resolution
    (_looks_like_resolution) dans la CLAUSE contenant le mot-cle -- ni le
    reste du message, ni une simple fenetre de caracteres fixe."""
    match = re.search(rf"\b{re.escape(keyword.lower())}\b", text)
    if match is None:
        return False
    clause = _clause_containing(text, match.start())
    return bool(_RESOLVED_STATE_PATTERN.search(clause) or _looks_like_resolution(clause))


def _filter_negated_or_resolved(
    text: Text, scored: List[Dict[Text, Any]], problems: List[Dict[Text, Any]]
) -> List[Dict[Text, Any]]:
    """Retire un candidat dont TOUS les mots-cles presents dans le message
    sont nies ou annonces resolus (voir _keyword_resolved_or_negated) -- le
    score par embedding (_score_capabilities_embeddings) n'a lui-meme AUCUNE
    notion de negation/resolution : il mesure une similarite semantique, pas
    une polarite grammaticale. Constate en pratique (grande vague de tests
    conversationnels) : "mon KYC n'est plus un souci, mais mon compte semble
    suspendu" gardait kyc_status_issue candidat (parfois meme gagnant net,
    empechant meme _apply_keyword_tiebreak de s'executer) malgre la negation
    explicite -- ce filtre s'applique AVANT le tiebreak et le rescue, sur
    TOUS les candidats, pas seulement en cas d'egalite.

    Un probleme dont AUCUN mot-cle n'apparait litteralement dans le message
    n'est jamais filtre ici (rien a nier/resoudre par mot-cle, la decision
    reste entierement au score semantique) -- seul un mot-cle explicitement
    present ET nie/resolu (au sens etroit de _keyword_resolved_or_negated,
    PAS de _keyword_matches/NEGATION_PATTERN, trop large pour ce role --
    voir son commentaire) declenche l'exclusion.
    """
    if not scored:
        return scored
    keywords_by_key = {(p["service"], p["id"]): p.get("keywords", []) for p in problems}
    filtered = []
    for candidate in scored:
        keywords = keywords_by_key.get((candidate["service_id"], candidate["problem_id"]), [])
        present_keywords = [kw for kw in keywords if _keyword_present(kw, text)]
        if present_keywords and all(_keyword_resolved_or_negated(kw, text) for kw in present_keywords):
            continue
        filtered.append(candidate)
    return filtered


# --- Repli semantique PAR PROPOSITION (pas par mot-cle) : quand AUCUN
# probleme ne franchit MIN_EMBEDDING_SIMILARITY sur le message entier, la
# cause la plus frequente n'est pas l'absence de signal mais sa DILUTION --
# une phrase a plusieurs propositions ("mon retrait est bloque depuis hier
# ET je voudrais comprendre pourquoi") produit un vecteur moyen entre la
# proposition qui porte reellement le probleme et celle qui ne fait que
# formuler une demande generique, ce qui eloigne le vecteur final de
# n'importe quelle reference precise (constate en pratique : "mon retrait
# est bloque" seul score 0.893, la meme idee avec "et je voudrais
# comprendre pourquoi" ajoute derriere tombe sous 0.83 et disparait des
# candidats).
#
# Plutot que de rattraper ça par des mots-cles metier (retrait/bloque...),
# on reessaie l'embedding sur chaque PROPOSITION prise separement : la
# segmentation ci-dessous ne connait que des connecteurs grammaticaux
# (et/mais/car/donc...), universels et indifferents au domaine -- ni la
# segmentation ni le score final ne savent ce qu'est un "retrait". Le
# meilleur score, toutes propositions confondues, l'emporte : c'est un
# second essai semantique, pas un filet lexical d'une autre nature.
_CLAUSE_CONNECTORS = re.compile(
    # "par contre"/"en revanche" ajoutes suite a la grande vague de tests
    # conversationnels (2026-07) : connecteurs contrastifs tres courants,
    # absents avant -- un message "ancien probleme resolu, PAR CONTRE
    # nouveau probleme" ne se segmentait jamais (_clause_candidates
    # renvoyait [], len(parts) < 2), donc le repli par clause
    # (_score_capabilities_embeddings_by_clause) ne s'executait jamais :
    # seul le score sur le message ENTIER (les 2 propositions melangees)
    # existait, diluant le signal du vrai nouveau probleme.
    r"\b(?:et|mais|car|donc|puis|puisque|alors que|cependant|parce que|par contre|en revanche)\b",
    re.IGNORECASE,
)


def _clause_candidates(text: Text) -> List[Text]:
    parts = [p.strip() for p in _CLAUSE_CONNECTORS.split(text) if p.strip()]
    if len(parts) < 2:
        # Rien a decouper (aucun connecteur) : la dilution, si elle existe,
        # ne vient pas d'une juxtaposition de propositions -- pas de sous-
        # decoupage pertinent a proposer ici.
        return []
    # Prefixe cumulatif (tout ce qui precede un connecteur donne) : capture
    # le sujet principal sans supposer laquelle des propositions le porte,
    # on les essaie toutes plutot que de choisir a priori laquelle est "la
    # bonne". Dedoublonne via set (le prefixe complet peut coincider avec
    # une proposition individuelle sur une phrase a 2 propositions).
    candidates = {" ".join(parts[:i]) for i in range(1, len(parts) + 1)}
    candidates.update(parts)
    return [c for c in candidates if len(c.split()) >= MIN_SEGMENT_WORDS]


def _score_capabilities_embeddings_by_clause(
    text: Text, problems: List[Dict[Text, Any]]
) -> List[Dict[Text, Any]]:
    clauses = _clause_candidates(text)
    if not clauses:
        return []
    clause_embeddings = _embed_messages(clauses)
    if not clause_embeddings:
        # Panne reseau sur le lot entier : pas de repli partiel clause par
        # clause ici (voir _embed_messages), le message entier a deja ete
        # tente juste avant par l'appelant (_score_capabilities).
        return []
    best_by_key: Dict[tuple, Dict[Text, Any]] = {}
    for clause_embedding in clause_embeddings:
        if clause_embedding is None:
            continue
        for candidate in _score_capabilities_embeddings(clause_embedding, problems):
            key = (candidate["service_id"], candidate["problem_id"])
            current_best = best_by_key.get(key)
            if current_best is None or candidate["confidence"] > current_best["confidence"]:
                best_by_key[key] = candidate
    scored = list(best_by_key.values())
    scored.sort(key=lambda item: (-item["confidence"], -item["match_ratio"], item["label"]))
    return scored


def _merge_best_capability_scores(
    a: List[Dict[Text, Any]], b: List[Dict[Text, Any]]
) -> List[Dict[Text, Any]]:
    best_by_key: Dict[tuple, Dict[Text, Any]] = {}
    for candidate in a + b:
        key = (candidate["service_id"], candidate["problem_id"])
        current_best = best_by_key.get(key)
        if current_best is None or candidate["confidence"] > current_best["confidence"]:
            best_by_key[key] = candidate
    merged = list(best_by_key.values())
    merged.sort(key=lambda item: (-item["confidence"], -item["match_ratio"], item["label"]))
    return merged


def _group_best_candidate_per_service(candidates: List[Dict[Text, Any]]) -> Dict[Text, Dict[Text, Any]]:
    # Le meilleur candidat par service_id, tous rangs confondus (pas
    # seulement un top-3 arbitraire) : le vrai meilleur representant d'un
    # service peut se trouver plus bas dans la liste si plusieurs candidats
    # d'un AUTRE service se sont glisses devant lui.
    best_by_service: Dict[Text, Dict[Text, Any]] = {}
    for candidate in candidates:
        service = candidate["service_id"]
        current_best = best_by_service.get(service)
        if current_best is None or candidate["confidence"] > current_best["confidence"]:
            best_by_service[service] = candidate
    return best_by_service


def _apply_service_family_tiebreak(
    candidates: List[Dict[Text, Any]], threshold: float = CLASSIFICATION_RELATIVE_MARGIN
) -> List[Dict[Text, Any]]:
    """Desambiguisation inter-services (cause #3, vague de tests 2026-07 --
    voir direct_explanation_test.py, 76.3% de reussite sur 97 explications
    directes et completes avant ce correctif). N'agit QUE quand la liste
    complete a deja echoue _has_meaningful_margin -- meme garde que
    _apply_keyword_tiebreak (voir plus bas) : un cas deja net n'entre jamais
    ici, zero risque de regression sur un verrouillage qui marchait deja.

    Le desaccord vient-il du fait que les candidats en tete appartiennent a
    des services DIFFERENTS (ex. un probleme wallet contre 1-2 problemes
    user) plutot que d'une vraie ambiguite a l'interieur d'UN service ? Si le
    meilleur candidat du service en tete devance le meilleur candidat du
    service suivant d'une marge relative >= `threshold`, restreint le bassin
    a ce seul service -- SANS decider elle-meme si le probleme precis est
    desormais clair : _apply_keyword_tiebreak puis _has_single_clear_winner,
    juste apres dans le pipeline, tranchent cette question exactement comme
    aujourd'hui, seulement sur un bassin plus petit et plus pertinent
    (candidats du bon service uniquement).

    Seuil : reutilise CLASSIFICATION_RELATIVE_MARGIN telle quelle (pas de
    nouvelle constante). Verifie contre un cas-canari qui DOIT rester
    ambigu -- "Mon retrait est en attente, ma recharge aussi, et mon compte
    semble suspendu." (3 vrais sujets, wallet + 2x user), ecart
    inter-services mesure = 1.827%, sous ce seuil de 2% : reste ambigu,
    comme aujourd'hui. Les echecs cibles par ce correctif se situent au-
    dessus (2.48%, 2.70%). Le chevauchement entre ce qu'on veut corriger et
    ce qui doit rester ambigu est une limite reelle du signal disponible,
    pas un oubli : baisser ce seuil pour recuperer plus de cas casserait
    aussi ce canari.
    """
    if not candidates or _has_meaningful_margin(candidates, threshold):
        return candidates
    best_by_service = _group_best_candidate_per_service(candidates)
    if len(best_by_service) < 2:
        # Ambiguite deja confinee a UN SEUL service : rien a departager ici
        # (vocabulaire trop generique au sein d'une meme famille, ex.
        # account_deletion_status -- hors scope de ce correctif).
        return candidates
    ranked_services = sorted(best_by_service.items(), key=lambda kv: -kv[1]["confidence"])
    (top_service, top_candidate), (_, runner_candidate) = ranked_services[0], ranked_services[1]
    if top_candidate["confidence"] <= 0:
        return candidates
    cross_service_margin = (
        top_candidate["confidence"] - runner_candidate["confidence"]
    ) / top_candidate["confidence"]
    if cross_service_margin < threshold:
        # Les deux services restent trop proches pour qu'on tranche a leur
        # place -- comportement actuel inchange, l'ambiguite remonte telle
        # quelle vers _mark_pending_choices.
        return candidates
    return [c for c in candidates if c["service_id"] == top_service]


def _score_capabilities(
    text: Text, problems: List[Dict[Text, Any]], apply_family_tiebreak: bool = True
) -> List[Dict[Text, Any]]:
    # Voie semantique par defaut ; repli automatique sur les mots-cles si le
    # service d'embeddings est injoignable OU si aucun probleme connu n'a
    # d'embedding precalcule (ex. juste apres l'ajout d'un service qui ne
    # declare pas encore de `description` dans son manifeste).
    problems_with_embeddings = [problem for problem in problems if problem.get("embedding")]
    if problems_with_embeddings:
        message_embedding = _embed_message(text)
        if message_embedding is not None:
            scored = _score_capabilities_embeddings(message_embedding, problems_with_embeddings)
            # Pas seulement "si `scored` est vide" : un message a plusieurs
            # propositions peut tres bien faire ressortir des candidats SANS
            # RAPPORT sur le message entier (la proposition secondaire
            # "pese" dans le vecteur moyen au point de rapprocher le
            # resultat d'un tout autre probleme) sans que `scored` soit vide
            # pour autant -- constate en pratique : "mon retrait est bloque
            # depuis hier et je voudrais comprendre pourquoi" ressortait 3
            # candidats sans rapport (0.885/0.875/0.871, aucun net) plutot
            # qu'une liste vide. Meme condition de declenchement
            # que _apply_keyword_tiebreak (_has_meaningful_margin) : le repli
            # par proposition n'est tente QUE si le message entier n'a pas
            # deja un gagnant net, pour ne payer l'appel d'embedding
            # supplementaire que quand il est utile.
            if not scored or not _has_meaningful_margin(scored, CLASSIFICATION_RELATIVE_MARGIN):
                clause_scored = _score_capabilities_embeddings_by_clause(text, problems_with_embeddings)
                # Fusion par MEILLEUR score par probleme, jamais par simple
                # remplacement : un candidat deja present sur le message
                # entier n'est jamais degrade par un score de proposition
                # plus faible, seulement complete ou renforce.
                scored = _merge_best_capability_scores(scored, clause_scored)
            # Filtre negation/resolution (voir _filter_negated_or_resolved) :
            # AVANT le tiebreak, applique a TOUS les candidats (pas seulement
            # en cas d'egalite) -- un probleme nie/resolu ne doit jamais
            # gagner, meme quand l'embedding lui donne un score net.
            scored = _filter_negated_or_resolved(text, scored, problems)
            if apply_family_tiebreak:
                # Avant le tiebreak mot-cle : une fois le bassin restreint a
                # un seul service, la fenetre scored[:3] du tiebreak ne peut
                # plus etre detournee par un mot generique d'un AUTRE
                # service (ex. "bloque" partage entre withdrawal_pending et
                # account_access_blocked).
                scored = _apply_service_family_tiebreak(scored, CLASSIFICATION_RELATIVE_MARGIN)
            scored = _apply_keyword_tiebreak(text, scored, problems)
            # Repechage par mot-cle unique (voir _rescue_unique_keyword_match) :
            # uniquement quand embeddings + repli par clause + tiebreak ont
            # TOUS echoue -- un cas deja tranche par l'un des trois ne passe
            # jamais par ici, aucun risque de regression sur ce qui marchait
            # deja.
            if not scored:
                rescued = _rescue_unique_keyword_match(text, message_embedding, problems_with_embeddings)
                if rescued is not None:
                    # _rescue_unique_keyword_match utilise _keyword_signal
                    # (base sur _keyword_matches, fenetre AVANT uniquement --
                    # voir son commentaire) qui ne voit pas une negation
                    # placee APRES le mot-cle ("KYC n'est plus bloque") :
                    # sans repasser par le meme filtre, le rescue ressuscitait
                    # exactement le candidat que _filter_negated_or_resolved
                    # venait de retirer (constate en pratique, grande vague de
                    # tests conversationnels, 3e passage).
                    scored = _filter_negated_or_resolved(text, [rescued], problems)
            return scored
    return _score_capabilities_keywords(text, problems)


# --- Segmentation multi-problemes (audit "robustesse comportementale",
# cas 2/35) : un message peut decrire PLUSIEURS problemes reels distincts
# ("je ne peux plus me connecter. Mon retrait est aussi en attente. Et mon
# KYC est rejete."), ou UN seul probleme noye dans du recit sans rapport
# (cas 1/33, message-fleuve). Dans les deux cas, scorer le message ENTIER
# dilue le signal utile -- ce module segmente donc le texte et score chaque
# segment independamment AVANT de decider s'il s'agit d'une ambiguite
# normale (voir _score_capabilities seul, inchangee) ou d'un vrai cas
# multi-probleme.
#
# Ponctuation forte UNIQUEMENT (pas de connecteurs comme "aussi"/"et puis") :
# une premiere version splittait aussi sur ces mots, mais "aussi" apparait
# tout autant comme simple adverbe A L'INTERIEUR d'une phrase deja isolee
# par un point ("Mon KYC a aussi ete refuse") que comme jonction entre deux
# phrases distinctes -- constate en pratique, cette sur-segmentation
# fragmentait "Mon KYC a aussi ete refuse" en "Mon KYC a" + "ete refuse",
# deux morceaux trop pauvres pour que l'un ou l'autre passe la marge de
# confiance, faisant disparaitre ce probleme des candidats au lieu de le
# detecter. Les exemples donnes pour ce cas d'usage separent deja chaque
# probleme par une ponctuation forte -- pas besoin d'un signal en plus.
_SEGMENT_SPLIT_PATTERN = re.compile(r"[.!?;\n]+")
# Sous ce nombre de mots, un segment est trop court pour porter un vrai
# probleme (ex. "Bonjour" ou "Ensuite j'ai") -- on l'ignore plutot que de le
# faire scorer pour rien.
MIN_SEGMENT_WORDS = 3
# Meme plafond que l'ancien `[:3]` en dur au site d'appel (ActionRunDiagnosticStep) :
# nomme ici pour eviter de dupliquer le nombre magique dans les deux chemins
# (segmente et non segmente) de _score_capabilities_multi.
MAX_CANDIDATES = 3
# Plafond volontairement plus large que MAX_PRIORITY_CHOICES (candidats
# ambigus sur UN message, voir plus bas) : un utilisateur qui enumere ses
# problemes en cite rarement plus de 4-5 dans un seul message.
MAX_SEGMENT_PROBLEMS = 4


def _segment_message(text: Text) -> List[Text]:
    raw_segments = _SEGMENT_SPLIT_PATTERN.split(text)
    return [
        segment.strip()
        for segment in raw_segments
        if segment and len(segment.strip().split()) >= MIN_SEGMENT_WORDS
    ]


def _score_capabilities_multi(text: Text, problems: List[Dict[Text, Any]]) -> tuple[List[Dict[Text, Any]], bool]:
    """Comme _score_capabilities, mais tente d'abord une segmentation.

    Audit qualite du code, cas #4 : la boucle ci-dessous appelle
    _score_capabilities une fois PAR SEGMENT (1 appel HTTP d'embedding
    chacun, potentiellement complete par le rescue par clause -- deja
    batche, voir _score_capabilities_embeddings_by_clause). Un message
    compte en pratique 2-4 segments (voir MAX_SEGMENT_PROBLEMS) : batcher
    aussi ce niveau exigerait de faire remonter un embedding precalcule a
    travers _score_capabilities (utilise par 4 autres appelants avec des
    besoins differents, voir sites d'appel), pour un gain marginal a
    l'echelle actuelle. Deferré : le rescue par clause ci-dessus, seule
    vraie boucle non bornee (autant de clauses que de connecteurs
    grammaticaux dans le message), etait le cas a fort volume reel.

    Retourne (candidats, multi_problemes_detectes). multi_problemes_detectes
    ne devient vrai que si au moins DEUX segments distincts produisent
    chacun un gagnant net (_has_meaningful_margin, meme seuil que le
    verrouillage normal) sur des capacites DIFFERENTES -- pas seulement
    plusieurs phrases dans le message.
    """
    segments = _segment_message(text)
    if len(segments) <= 1:
        # Rien a segmenter (message court ou deja une seule phrase) :
        # comportement strictement inchange par rapport a avant ce fix.
        return _score_capabilities(text, problems)[:MAX_CANDIDATES], False

    distinct_winners: List[Dict[Text, Any]] = []
    winning_candidates_by_segment: List[List[Dict[Text, Any]]] = []
    seen_keys = set()
    for segment in segments:
        segment_candidates = _score_capabilities(segment, problems)
        if not segment_candidates or not _has_meaningful_margin(segment_candidates, CLASSIFICATION_RELATIVE_MARGIN):
            continue
        best = segment_candidates[0]
        key = (best["service_id"], best["problem_id"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        distinct_winners.append(best)
        winning_candidates_by_segment.append(segment_candidates[:MAX_CANDIDATES])
        if len(distinct_winners) >= MAX_SEGMENT_PROBLEMS:
            break

    if not distinct_winners:
        # Segmentation infructueuse (aucun segment assez net individuellement) :
        # repli sur le score du message entier, comme avant ce fix.
        return _score_capabilities(text, problems)[:MAX_CANDIDATES], False
    if len(distinct_winners) == 1:
        # Un seul probleme reel identifie malgre plusieurs segments (cas
        # 1/33) : on retourne le classement complet de CE segment precis
        # (pas du message entier, dilue par le recit autour) -- l'utilisateur
        # n'a jamais besoin de savoir qu'une segmentation a eu lieu ici, le
        # comportement percu est juste "le bruit a ete ignore".
        return winning_candidates_by_segment[0], False
    # 2+ problemes distincts et nets : vrai cas multi-probleme (cas 2/35).
    return distinct_winners, True


# Permet a l'utilisateur de choisir entre plusieurs capacites candidates par
# un numero ou un mot ordinal, en plus du nom du probleme.
ORDINAL_WORDS: Dict[Text, int] = {
    "1": 0, "un": 0, "premier": 0, "première": 0,
    "2": 1, "deux": 1, "deuxième": 1, "second": 1, "seconde": 1,
    "3": 2, "trois": 2, "troisième": 2,
}


def _match_pending_choice(text: Text, choices: List[Dict[Text, Any]]) -> Dict[Text, Any] | None:
    lowered = text.lower()
    for word, index in ORDINAL_WORDS.items():
        if word in lowered and index < len(choices):
            return choices[index]
    return next((choice for choice in choices if choice["label"].lower() in lowered), None)


def _search_pattern_match(pattern: Text, value: Text) -> Text | None:
    # Les patterns du manifeste sont ancres (^...$) pour valider un texte
    # entier -- les garder tels quels exigerait que TOUT le message
    # corresponde, ce qui annule l'interet d'une recherche dans une phrase
    # naturelle. On retire les ancres pour chercher la sous-chaine
    # correspondante n'importe ou dans le texte, et on prend la PLUS LONGUE
    # trouvee (une regex generique matche aussi des mots ordinaires plus
    # courts, ex. "pense" avant la vraie valeur "WDR-XXXX").
    search_pattern = pattern
    if search_pattern.startswith("^"):
        search_pattern = search_pattern[1:]
    if search_pattern.endswith("$"):
        search_pattern = search_pattern[:-1]
    matches = [m.group(0) for m in re.finditer(search_pattern, value)]
    return max(matches, key=len) if matches else None


def _looks_like_identifier(value: Text) -> bool:
    # Un pattern generique de type identifiant (ex. [A-Za-z0-9_-]{3,64}) matche
    # aussi bien "WDR-HJCOZRCVCOAY" qu'un mot francais ordinaire ("retrait",
    # "correspondant"...) puisque les deux sont de simples suites de lettres.
    # Toutes les references reelles du catalogue (WDR-, TOPUP-, GFT-)
    # contiennent un chiffre ou un separateur ; un mot du langage courant n'en
    # contient quasiment jamais -- filtre cible sans dictionnaire, utilise a la
    # fois pour la capture opportuniste et pour la reponse explicite.
    return any(char.isdigit() or char in "-_" for char in value)


def _capture_opportunistic_field_patterns(
    state: Dict[Text, Any], confirmed: Dict[Text, Any], message_text: Text
) -> None:
    # Meme principe que la capture opportuniste par entite NLU dans
    # _extract_field_answer, mais par pattern de manifeste (FieldSpec.pattern) :
    # un champ comme transaction_reference n'a jamais d'entite NLU annotee
    # (aucun exemple de ce type dans nlu.yml), sa seule extraction possible
    # est ce pattern -- jusqu'ici tente uniquement APRES que le champ ait ete
    # explicitement demande (waiting_for). Sans ceci, une reference deja
    # donnee dans le tout premier message ("mon retrait est bloque depuis
    # hier, voici WDR-XXXX") etait ignoree : le bot la redemandait juste
    # apres alors qu'elle etait deja la. Appele au moment ou un probleme est
    # (re)verrouille, sur le texte BRUT du message qui vient d'etre classe.
    if not message_text:
        return
    field_specs = state.get("field_specs") or {}
    known_fields = (
        set(state.get("required_fields", []))
        | set(state.get("optional_fields", []))
        | set(state.get("fallback_fields", []))
    )
    for field in known_fields:
        if field in confirmed:
            continue
        pattern = field_specs.get(field, {}).get("pattern")
        if not pattern:
            continue
        match = _search_pattern_match(pattern, message_text)
        # Voir _looks_like_identifier : le message n'a jamais ete demande a
        # CONTENIR ce champ ici, un simple "plus long match" suffirait a
        # capturer un mot francais ordinaire (constate en test : "Mon retrait
        # est bloque depuis hier" capturait "retrait" comme transaction_reference).
        if match and _looks_like_identifier(match):
            confirmed[field] = match


def _capture_opportunistic_nlu_entities(
    state: Dict[Text, Any], confirmed: Dict[Text, Any], entities: List[Dict[Text, Any]]
) -> None:
    # Meme principe que _capture_opportunistic_field_patterns juste au-dessus,
    # mais pour les entites NLU (operation_type, issue_status, amount,
    # incident_date, platform -- voir nlu.yml) plutot qu'un pattern de
    # manifeste. Avant cet ajout, _extract_field_answer etait le SEUL endroit
    # qui lisait ces entites, et il ne tourne que si `waiting_for` est deja
    # pose (voir ActionRunDiagnosticStep) -- jamais au tout premier message,
    # qui est pourtant celui ou l'utilisateur donne le plus spontanement ce
    # genre d'info ("mon retrait est bloque depuis hier"). Appele au moment
    # ou un probleme est (re)verrouille, sur les entites du message qui vient
    # d'etre classe (voir state["message_entities"], ActionRunDiagnosticStep)
    # -- symetrique de l'appel a _capture_opportunistic_field_patterns juste
    # au-dessus.
    known_fields = (
        set(state.get("required_fields", []))
        | set(state.get("optional_fields", []))
        | set(state.get("fallback_fields", []))
    )
    for entity in entities:
        field_name = entity.get("entity")
        if field_name not in known_fields or field_name in confirmed:
            continue
        value = entity.get("value")
        if value is not None:
            confirmed[field_name] = value


def _next_missing_field(required_fields: List[Text], confirmed: Dict[Text, Any]) -> Text:
    return next((field for field in required_fields if not confirmed.get(field)), "")


def _next_step(required_fields: List[Text], confirmed: Dict[Text, Any], diagnostic_confirmed: bool) -> Text:
    # Une fois tous les champs requis collectes, on ne resout/escalade plus
    # immediatement : on marque d'abord une etape de confirmation (voir
    # "diagnostic_confirmation" dans STATE_HANDLERS/RESPONSE_HANDLERS), pour
    # laisser a l'utilisateur une chance de voir un recapitulatif et de
    # corriger avant l'appel au moteur -- symetrique de ce qui existe deja
    # pour la reclamation (action_request_reclamation_confirmation).
    missing = _next_missing_field(required_fields, confirmed)
    if missing:
        return missing
    if not diagnostic_confirmed:
        return "diagnostic_confirmation"
    return ""


# Prefixe partage par les 2 placeholders de _handle_field_answer (refus /
# incertitude) : marque un champ EXPLICITEMENT non repondu par l'utilisateur,
# jamais une vraie valeur -- filtre juste en dessous avant envoi au
# microservice externe, qui attend une valeur typee (montant, reference...)
# pour ces memes champs, pas une phrase humaine.
UNRESOLVED_FIELD_PLACEHOLDER_PREFIX = "Non communiqué"


def _entities_for_engine(confirmed: Dict[Text, Any]) -> Dict[Text, Any]:
    return {
        key: value
        for key, value in confirmed.items()
        if not (isinstance(value, str) and value.startswith(UNRESOLVED_FIELD_PLACEHOLDER_PREFIX))
    }


# Nombre de pannes techniques CONSECUTIVES (voir _respond_engine_outcome)
# tolerees avant de proposer un ticket -- 1re panne = simple message
# d'attente/reessai, 2e panne d'affilee = on cesse d'inviter a reessayer et
# on transmet a l'equipe technique (meme principe que le rapport : "l'escalade
# ne doit intervenir que si plusieurs tentatives echouent").
ENGINE_UNAVAILABLE_ESCALATION_THRESHOLD = 2

ENGINE_UNAVAILABLE_MESSAGES: Dict[Text, Text] = {
    "timeout": (
        "Je rencontre actuellement une difficulté pour accéder à votre dossier. "
        "Le service semble temporairement indisponible. Merci de réessayer dans quelques instants."
    ),
    "http_error": (
        "Une erreur interne est survenue lors de la récupération de vos informations. "
        "Je vous invite à réessayer dans quelques minutes."
    ),
}


def _call_diagnostic_engine(tracker: Tracker, state: Dict[Text, Any]) -> Dict[Text, Any]:
    payload = {
        "session_id": tracker.sender_id,
        "service": state.get("service_id"),
        "problem": state.get("template_id"),
        "entities": _entities_for_engine(state.get("confirmed") or {}),
    }
    try:
        response = request_with_retry(
            "POST",
            DIAGNOSTIC_SERVICE_URL,
            json=payload,
            headers={"X-User-ID": tracker.sender_id},
            timeout=10,
        )
        result = response.json()
        return result
    except (requests.Timeout, requests.ConnectionError) as exc:
        # Distinct de l'erreur HTTP ci-dessous (audit robustesse UX, cas
        # "panne technique confondue avec escalade metier") : ni timeout ni
        # panne reseau ne sont une decision du moteur de diagnostic --
        # _respond_engine_outcome ne doit PAS proposer un ticket dans le
        # meme message que pour un vrai outcome ESCALATE, sinon une panne
        # transitoire se presente a l'utilisateur exactement comme si son
        # dossier avait ete reellement examine puis escalade.
        logger.warning(
            "Timeout/panne reseau vers le moteur de diagnostic (%s) session=%s service=%s problem=%s : %s",
            DIAGNOSTIC_SERVICE_URL, tracker.sender_id, payload.get("service"), payload.get("problem"), exc,
        )
        return {"outcome": "_ENGINE_UNAVAILABLE", "kind": "timeout"}
    except requests.RequestException as exc:
        # Jamais les entities du payload ici (peuvent contenir des donnees
        # sensibles -- montant, reference de transaction... -- voir
        # app.shared.logging_utils.redact_entities cote FastAPI, meme
        # principe) : seuls service/problem/session, jamais des valeurs.
        # Regroupe les 5xx (deja retries par request_with_retry) et tout
        # autre echec HTTP inattendu -- meme traitement cote
        # _respond_engine_outcome que le timeout ci-dessus (panne technique,
        # pas une decision metier).
        logger.warning(
            "Echec d'appel au moteur de diagnostic (%s) session=%s service=%s problem=%s : %s",
            DIAGNOSTIC_SERVICE_URL, tracker.sender_id, payload.get("service"), payload.get("problem"), exc,
        )
        return {"outcome": "_ENGINE_UNAVAILABLE", "kind": "http_error"}


# Question posee quand un required_field du probleme resolu manque encore.
# Prioritaire sur la description du manifeste (field_specs) quand elle
# existe ; sinon, la description renvoyee par /diagnostic/capabilities sert
# de question de repli -- ajouter un champ a un manifeste ne demande donc
# aucune modification ici.
#
# Chaque champ porte 2 formulations (audit UX, 2026-07, point A1) : sans ca,
# un diagnostic qui redemande le meme champ (invalid_field_attempt, ou apres
# une reprise post-interruption) posait mot pour mot la meme question,
# contrastant avec le reste des reponses deja variees (domain.yml). La 1ere
# variante de chaque liste reste la forme CANONIQUE, seule utilisee par
# _describe_pending_question (fragment de phrase inline, pas une question
# affichee telle quelle -- y introduire une 2e variante casserait sa
# grammaire, voir son propre commentaire) via _field_question_canonical.
FIELD_QUESTIONS: Dict[Text, List[Text]] = {
    "issue_status": [
        "Où en est ce problème : en attente, échoué ou bloqué ?",
        "Ce problème est-il en attente, échoué, ou bloqué ?",
    ],
    "amount": [
        "Quel est le montant concerné ?",
        "Pouvez-vous préciser le montant concerné ?",
    ],
    # Nom aligne sur l'entite NLU "incident_date" (nlu.yml), pas "date" :
    # _capture_opportunistic_nlu_entities/_extract_field_answer matchent par
    # egalite exacte entre nom de champ de manifeste et nom d'entite NLU.
    "incident_date": [
        "À quelle date (ou depuis quand) le problème s’est-il produit ?",
        "Depuis quand rencontrez-vous ce problème ?",
    ],
    "device": [
        "Sur quelle plateforme rencontrez-vous ce problème ? (Android, iOS, Web)",
        "Vous êtes sur quelle plateforme : Android, iOS, ou le site Web ?",
    ],
    "payment_method": [
        "Quel moyen de paiement avez-vous utilisé ?",
        "Pouvez-vous préciser le moyen de paiement utilisé ?",
    ],
    "description": [
        "Pouvez-vous décrire le problème plus précisément ?",
        "Pouvez-vous m'en dire un peu plus sur ce problème ?",
    ],
    "transaction_reference": [
        "Avez-vous une référence de transaction ou de ticket ?",
        "Auriez-vous la référence de la transaction ou du ticket concerné ?",
    ],
    "time": [
        "À quelle heure environ le problème est-il survenu ?",
        "Vous souvenez-vous à quelle heure c'est arrivé ?",
    ],
    "content_type": [
        "Quel type de contenu est concerné ?",
        "Pouvez-vous préciser le type de contenu concerné ?",
    ],
    "video_id": [
        "Avez-vous l’identifiant ou le lien de la vidéo concernée ?",
        "Pouvez-vous partager l'identifiant ou le lien de la vidéo concernée ?",
    ],
    "last_message": [
        "Quel était le dernier message reçu ou envoyé ?",
        "Vous souvenez-vous du dernier message reçu ou envoyé ?",
    ],
    "severity": [
        "Diriez-vous que la gravité est faible, moyenne ou élevée ?",
        "Sur une échelle faible/moyenne/élevée, comment évalueriez-vous la gravité ?",
    ],
    "document_type": [
        "Quel type de document est concerné ?",
        "Pouvez-vous préciser le type de document concerné ?",
    ],
    "country": [
        "Dans quel pays est basé votre compte ?",
        "Votre compte est basé dans quel pays ?",
    ],
    "subscription_type": [
        "Quel abonnement est concerné ?",
        "Pouvez-vous préciser quel abonnement est concerné ?",
    ],
    "channel": [
        "Sur quel canal recevez-vous (ou non) cette notification ?",
        "Cette notification concerne quel canal ?",
    ],
    "contact_channel": [
        "Par quel canal souhaitez-vous être recontacté ?",
        "Comment préférez-vous qu'on vous recontacte ?",
    ],
    "urgency": [
        "Quel est le niveau d’urgence : faible, moyenne ou élevée ?",
        "Diriez-vous que c'est urgent, moyennement urgent, ou pas urgent ?",
    ],
}


def _field_question(field_name: Text, fallback: Text) -> Text:
    variants = FIELD_QUESTIONS.get(field_name)
    return pick(*variants) if variants else fallback


def _field_question_canonical(field_name: Text) -> Optional[Text]:
    # Seule la 1ere variante (voir le commentaire de FIELD_QUESTIONS) : cet
    # appelant compose un FRAGMENT de phrase inline (_describe_pending_question),
    # pas une question affichee telle quelle -- y introduire une 2e variante
    # casserait sa grammaire sans que ce soit visible ici.
    variants = FIELD_QUESTIONS.get(field_name)
    return variants[0] if variants else None

# Libelles courts (pas des questions completes) pour le recapitulatif avant
# verification (voir _respond_diagnostic_confirmation) -- audit ton/clarite :
# ce recap affichait auparavant les noms de champs BRUTS du manifeste
# ("transaction_reference : ...", "payment_method : ...") tels quels.
FIELD_LABELS: Dict[Text, Text] = {
    "issue_status": "statut",
    "amount": "montant",
    "incident_date": "date",
    "device": "plateforme",
    "payment_method": "moyen de paiement",
    "description": "description",
    "transaction_reference": "référence",
    "time": "heure",
    "content_type": "type de contenu",
    "video_id": "vidéo concernée",
    "last_message": "dernier message",
    "severity": "gravité",
    "document_type": "type de document",
    "country": "pays",
    "subscription_type": "abonnement",
    "channel": "canal",
    "contact_channel": "canal de contact",
    "urgency": "urgence",
}


class _DiagnosticContext:
    """Regroupe tout ce dont les handlers ci-dessous ont besoin, pour eviter
    des signatures a rallonge et permettre un dispatch par dictionnaire
    (meme signature pour tous les handlers d'une meme table) plutot que des
    chaines de if/elif. `state` et `confirmed` sont mutes en place par les
    handlers (jamais reassignes), pour que les changements soient visibles
    par le reste de `ActionRunDiagnosticStep.run()` sans valeur de retour.
    """

    __slots__ = ("dispatcher", "tracker", "state", "confirmed", "text")

    def __init__(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        state: Dict[Text, Any],
        confirmed: Dict[Text, Any],
        text: Text,
    ):
        self.dispatcher = dispatcher
        self.tracker = tracker
        self.state = state
        self.confirmed = confirmed
        self.text = text


# --- Extraction (ex action_extract_diagnostic_entities) : un handler par
# valeur possible de `waiting_for`, plus un handler par defaut pour un nom de
# champ metier arbitraire (impossible a lister a l'avance, vient du
# manifeste dynamique). Remplace la chaine if/elif precedente par un
# dictionnaire consulte via .get() : ajouter un nouveau pseudo-champ = ajouter
# une entree, sans toucher aux autres.

def _extract_priority_choice(ctx: _DiagnosticContext) -> None:
    # Le tour precedent proposait plusieurs capacites candidates : on essaie
    # de resoudre laquelle l'utilisateur vient de choisir (par numero/ordinal
    # ou par nom), independamment du scoring de _score_capabilities (ce
    # message ne parle probablement plus du probleme).
    choices = ctx.state.get("pending_choices", [])
    chosen = _match_pending_choice(ctx.text, choices)
    if chosen:
        ctx.state["chosen_candidate"] = chosen


def _extract_diagnostic_confirmation(ctx: _DiagnosticContext) -> None:
    # Reponse au recapitulatif (voir _next_step) : une negation relance la
    # collecte depuis le debut plutot que d'envoyer au moteur des
    # informations que l'utilisateur vient de rejeter -- pas de correction
    # champ par champ (hors scope, cf. roadmap), mais au moins l'occasion de
    # tout reprendre si quelque chose est faux. On verifie d'abord
    # l'intention classee (deny) -- fiable sur une reponse courte de ce type
    # (contrairement a NEGATION_PATTERN, concu pour une negation noyee dans
    # une phrase plus longue, ex. "je n'ai plus besoin d'aide" ; "non" seul ne
    # matche aucun de ses motifs) -- puis NEGATION_PATTERN en repli pour une
    # formulation plus longue non couverte par l'intention.
    intent_name = (ctx.tracker.latest_message.get("intent") or {}).get("name")
    if intent_name == "deny" or NEGATION_PATTERN.search(ctx.text):
        ctx.dispatcher.utter_message(text="D'accord, reprenons la collecte des informations depuis le début.")
        ctx.confirmed.clear()
        ctx.state["diagnostic_confirmed"] = False
    elif intent_name == "affirm":
        ctx.state["diagnostic_confirmed"] = True
    else:
        # Ni "oui" ni "non" reconnu (ex. question hors-sujet, intention mal
        # classee comme inappropriate_language/nlu_fallback -- toutes deux
        # relancent action_run_diagnostic_step pendant qu'un pending_field
        # est actif, voir "Ignore nlu_fallback/deny/affirm misclassification
        # while diagnostic dialogue is pending" dans rules.yml, qui couvre
        # aussi bien la collecte de champs que cette etape de confirmation) :
        # NE PAS supposer une confirmation implicite. Avant ce correctif,
        # tout texte qui n'etait pas explicitement reconnu comme une
        # negation tombait dans le else et etait traite comme un "oui"
        # silencieux -- ce qui appelait le moteur de verification avec un
        # contexte errone. Trouve par test conversationnel (2026-07-18) :
        # "tu sais faire quoi d'autre au juste" ou "quelle heure est-il"
        # pendant la confirmation finale declenchaient l'appel au moteur
        # (erreur backend brute affichee, "Identifiant utilisateur
        # invalide"), puis une proposition de creer un ticket -- un simple
        # "oui"/"non" ensuite creait ou annulait une reclamation que
        # l'utilisateur n'avait jamais demandee. diagnostic_confirmed reste
        # False ici : _next_step (voir plus haut) redemande alors simplement
        # la confirmation, sans jamais appeler le moteur.
        ctx.state["diagnostic_confirmed"] = False
        ctx.dispatcher.utter_message(text="Je n'ai pas bien compris : répondez par oui ou par non pour confirmer.")


def _extract_service_narrowing(ctx: _DiagnosticContext) -> None:
    # Reponse a la question de repli posee par _mark_no_capability_matched
    # (Phase 4) quand le matching initial echoue mais que plusieurs services
    # existent dans le manifeste. On ne retente PAS le matching sur cette
    # reponse elle-meme (ex. "Wallet") : elle ne decrit pas le probleme, ne
    # sert qu'a identifier le service. Le matching est retente sur le message
    # ORIGINAL qui avait echoue -- state["message"] a ce stade contient
    # encore celui du tour precedent, puisqu'il n'est reecrase qu'apres
    # l'extraction (voir ActionRunDiagnosticStep.run()).
    services = ctx.state.get("known_services", [])
    chosen_service = _match_service_name(ctx.text, services)
    ctx.state["narrowing_attempted"] = True
    if chosen_service is None:
        # Service non reconnu dans la reponse : on abandonne le narrowing
        # (narrowing_attempted=True empeche une 2e tentative) et on retombe
        # sur le comportement standard "aucune capacite reconnue" au
        # prochain passage dans _mark_no_capability_matched.
        return

    original_text = (ctx.state.get("message") or "").lower()
    problems = _fetch_capabilities() or []
    restricted = [problem for problem in problems if problem.get("service") == chosen_service]
    candidates = _score_capabilities(original_text, restricted)
    if candidates:
        ctx.state["chosen_candidate"] = candidates[0]


def _extract_field_answer(ctx: _DiagnosticContext) -> None:
    # Handler par defaut : n'importe quel nom de champ metier venant d'un
    # manifeste dynamique (transaction_reference, amount, ...), impossible a
    # enumerer a l'avance dans EXTRACTION_HANDLERS.
    waiting_for = ctx.state.get("waiting_for")

    # Capture opportuniste : une reponse peut contenir plusieurs informations
    # utiles d'un coup (ex. "depuis hier, 500 pieces, en attente" repond a
    # incident_date/amount/issue_status en une seule fois). On stocke toute
    # entite NLU reconnue dont le nom correspond a un champ du probleme en
    # cours -- pas seulement celui explicitement demande -- pour ne pas
    # perdre cette information et eviter une question inutile plus tard.
    known_fields = set(ctx.state.get("required_fields", [])) | set(ctx.state.get("optional_fields", []))
    for entity in ctx.tracker.latest_message.get("entities", []):
        field_name = entity.get("entity")
        if field_name not in known_fields or field_name == waiting_for:
            continue
        new_value = entity.get("value")
        old_value = ctx.confirmed.get(field_name)
        if old_value is None:
            ctx.confirmed[field_name] = new_value
        elif new_value != old_value:
            # Correction implicite d'un champ deja confirme (audit
            # "robustesse comportementale", cas 12/13) : avant ce fix, ce
            # garde (`field_name not in ctx.confirmed`) empechait TOUTE mise
            # a jour d'un champ deja rempli, meme quand l'utilisateur venait
            # clairement de le corriger ("c'etait hier" -> "non en fait il y
            # a trois semaines") -- l'ancienne valeur restait silencieusement
            # en place, contradiction jamais reconciliee. Accuse de reception
            # generique (pas de libelle par champ ici, FIELD_QUESTIONS
            # contient des QUESTIONS pas des noms courts) pour que la
            # correction soit visible plutot que silencieuse.
            ctx.confirmed[field_name] = new_value
            ctx.dispatcher.utter_message(text="Noté, je mets à jour cette information.")

    # Champ en attente : on prend une entite NLU du meme nom si elle existe
    # (rare, aucun manifeste actuel n'en declare), sinon on capture verbatim
    # la reponse a la question qu'on venait de poser.
    entity_value = next(
        (
            entity.get("value")
            for entity in ctx.tracker.latest_message.get("entities", [])
            if entity.get("entity") == waiting_for
        ),
        None,
    )
    value = entity_value if entity_value is not None else ctx.tracker.latest_message.get("text")

    # Refus de repondre / incertitude (cas 7 et 31) : verifie AVANT toute
    # tentative d'extraction, sur le texte BRUT de la reponse (pas `value`,
    # qui peut deja avoir ete remplace par une entite NLU) -- dans les deux
    # cas, la reponse n'est explicitement PAS une valeur pour le champ, donc
    # aucune extraction (pattern ou texte libre) ne doit etre tentee.
    # Sentinelle non vide (pas None) stockee dans `confirmed` : _next_missing_field
    # ne redemande alors plus ce champ, contrairement a None qui boucle
    # indefiniment sur la meme question -- exactement le comportement que
    # ce fix doit eviter. Prefixe UNRESOLVED_FIELD_PLACEHOLDER_PREFIX partage
    # par les deux placeholders ci-dessous (audit robustesse) : _call_diagnostic_engine
    # filtre desormais tout champ commencant par ce prefixe avant l'envoi au
    # microservice externe, qui attend une valeur TYPEE (montant, reference...)
    # pour ces memes champs -- sans ce filtre, cette phrase humaine partait
    # telle quelle comme donnee metier, et un rejet 4xx du microservice sur ce
    # champ mal type se confondait avec une vraie panne reseau.
    raw_text = (ctx.tracker.latest_message.get("text") or "").lower()

    if _looks_like_cannot_provide_field(raw_text):
        # Rapport utilisateur, "champs alternatifs" : distinct du refus/de
        # l'incertitude ci-dessous ("je ne l'ai pas" = l'utilisateur ne
        # POSSEDE pas cette information precise, pas qu'il refuse de repondre
        # ou qu'il soit incertain d'une valeur qu'il pourrait donner).
        fallback_fields = ctx.state.get("fallback_fields") or []
        if fallback_fields and not ctx.state.get("_using_fallback_fields"):
            # Bascule required_fields -> fallback_fields : _continue_locked_template,
            # appele juste apres cette extraction dans le meme tour (voir
            # ActionRunDiagnosticStep.run()), recalculera waiting_for sur ce
            # nouvel ensemble via _next_step.
            ctx.state["required_fields"] = fallback_fields
            ctx.state["_using_fallback_fields"] = True
            ctx.state.pop("invalid_field_attempt", None)
            ctx.dispatcher.utter_message(
                text="Pas de souci, je vais vous demander d'autres informations à la place."
            )
            return
        if ctx.state.get("_using_fallback_fields"):
            # Deja en repli (le groupe de secours lui-meme ne peut pas non
            # plus etre fourni) : plus aucune voie de collecte possible, on
            # arrete le diagnostic ici plutot que de redemander indefiniment.
            # _continue_locked_template ne doit PAS ecraser ce waiting_for
            # (voir le garde correspondant, meme fichier).
            ctx.state["no_capability_matched"] = True
            ctx.state["no_capability_matched_reason"] = "fields_unavailable"
            ctx.state["waiting_for"] = ""
            return
        # Pas de repli declare pour ce probleme : retombe sur le
        # comportement existant (incertitude/refus, ou capture litterale).

    if _looks_like_refusal(raw_text):
        ctx.confirmed[waiting_for] = f"{UNRESOLVED_FIELD_PLACEHOLDER_PREFIX} (l'utilisateur a préféré ne pas répondre)"
        ctx.state.pop("invalid_field_attempt", None)
        ctx.dispatcher.utter_message(
            text="Pas de souci, je n'insiste pas sur ce point et je continue avec le reste."
        )
        return
    if _looks_like_uncertain(raw_text):
        ctx.confirmed[waiting_for] = f"{UNRESOLVED_FIELD_PLACEHOLDER_PREFIX} (information incertaine pour l'utilisateur)"
        ctx.state.pop("invalid_field_attempt", None)
        ctx.dispatcher.utter_message(
            text="Pas de problème si vous n'êtes pas certain, je continue avec les informations disponibles."
        )
        return

    # Extraction par format, definie par le manifeste (FieldSpec.pattern) :
    # cherche toutes les sous-chaines qui correspondent N'IMPORTE OU dans la
    # reponse, au lieu d'exiger que tout le message corresponde depuis le
    # debut (re.match). Sans ca, une reponse naturelle comme "je pense que
    # c'est WDR-XXXX" etait rejetee a tort. Absence de pattern = aucune
    # contrainte, la valeur brute est acceptee telle quelle (cas des champs
    # libres, ex. description).
    spec = (ctx.state.get("field_specs") or {}).get(waiting_for, {})
    pattern = spec.get("pattern")
    if pattern and value is not None:
        # Extraction par format, definie par le manifeste (FieldSpec.pattern) :
        # cherche N'IMPORTE OU dans la reponse (voir _search_pattern_match),
        # pas seulement un match exact -- sans ca, une reponse naturelle
        # comme "je pense que c'est WDR-XXXX" etait rejetee a tort.
        # _looks_like_identifier rejette un mot francais ordinaire qui matche
        # aussi le pattern generique (constate en test : une reponse hors
        # sujet capturait "correspondant" comme reference) -- traite comme un
        # format invalide, pas comme une valeur acceptee a tort.
        match = _search_pattern_match(pattern, value)
        if match and _looks_like_identifier(match):
            ctx.confirmed[waiting_for] = match
            ctx.state.pop("invalid_field_attempt", None)
        else:
            ctx.state["invalid_field_attempt"] = waiting_for
    else:
        # Absence de pattern = aucune contrainte de FORMAT, mais un plafond
        # de longueur reste applique (audit "robustesse comportementale",
        # cas 38/39) : sans lui, un champ libre sans pattern (ex.
        # description) acceptait un texte de taille arbitraire, surface
        # triviale d'epuisement de ressources sur un formulaire qui peut
        # boucler plusieurs fois.
        if isinstance(value, str) and len(value) > MAX_FIELD_ANSWER_LENGTH:
            value = value[:MAX_FIELD_ANSWER_LENGTH]
            ctx.dispatcher.utter_message(
                text=f"Votre réponse était longue, je l'ai raccourcie aux {MAX_FIELD_ANSWER_LENGTH} premiers caractères."
            )
        ctx.confirmed[waiting_for] = value
        ctx.state.pop("invalid_field_attempt", None)


EXTRACTION_HANDLERS: Dict[Text, Callable[[_DiagnosticContext], None]] = {
    "priority_choice": _extract_priority_choice,
    "diagnostic_confirmation": _extract_diagnostic_confirmation,
    "service_narrowing": _extract_service_narrowing,
}


# --- Classification/verrouillage (ex action_update_diagnostic_state) : liste
# ordonnee de (condition, action), evaluee dans l'ordre -- remplace la chaine
# if/elif imbriquee precedente par une table qu'on peut inspecter/etendre
# sans toucher a un bloc existant. La premiere condition vraie l'emporte,
# comme un if/elif, mais la sequence de regles est desormais une donnee (une
# liste), pas une structure de controle figee dans le code.

def _known_services(problems: List[Dict[Text, Any]]) -> List[Text]:
    # Ordre d'apparition dans la reponse /diagnostic/capabilities, dedoublonne
    # -- pas d'ordre alphabetique impose, pour rester simple.
    seen: List[Text] = []
    for problem in problems:
        service = problem.get("service")
        if service and service not in seen:
            seen.append(service)
    return seen


# Libelles humains des noms de service internes (voir services_registry.yaml,
# name: wallet/user) : ces noms bruts n'ont jamais ete destines a
# l'utilisateur final (meme raisonnement que FAQ_CATEGORY_LABELS dans
# faq.py), mais _respond_service_narrowing les affichait tels quels
# ("Est-ce plutôt lié à : wallet, user ?"). Trouve par test conversationnel
# (505 tours, 2026-07-18). SERVICE_MATCH_KEYWORDS etend _match_service_name
# en consequence : sans ca, un utilisateur qui reprend le libelle humain
# affiche ("mon portefeuille") plutot que le nom interne ne serait plus
# reconnu du tout.
SERVICE_LABELS: Dict[Text, Text] = {
    "wallet": "votre portefeuille",
    "user": "votre compte",
}

SERVICE_MATCH_KEYWORDS: Dict[Text, List[Text]] = {
    "wallet": ["wallet", "portefeuille", "porte-monnaie", "porte monnaie"],
    "user": ["user", "compte", "profil"],
}


def _service_label(service: Text) -> Text:
    return SERVICE_LABELS.get(service, service)


def _join_or(items: List[Text]) -> Text:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " ou " + items[-1]


def _match_service_name(text: Text, services: List[Text]) -> Text | None:
    lowered = text.lower()
    for service in services:
        keywords = SERVICE_MATCH_KEYWORDS.get(service, [service])
        if any(keyword in lowered for keyword in keywords):
            return service
    return None


def _has_pending_choices(state: Dict[Text, Any], candidates: List[Dict[Text, Any]]) -> bool:
    return bool(state.get("pending_choices"))


def _has_multiple_distinct_problems(state: Dict[Text, Any], candidates: List[Dict[Text, Any]]) -> bool:
    # Positionne AVANT _has_single_clear_winner dans CLASSIFICATION_RULES :
    # sans cette priorite, deux problemes distincts detectes par segmentation
    # (voir _score_capabilities_multi) mais dont les confidences respectives
    # different suffisamment l'un de l'autre passeraient le test de marge de
    # _has_single_clear_winner comme s'il s'agissait d'UNE SEULE
    # interpretation ambigue -- verrouillant silencieusement le premier et
    # perdant le second, exactement ce que ce fix doit eviter (audit
    # "robustesse comportementale", cas 2/35).
    return bool(state.get("_multi_problem_detected"))


def _lock_priority_choice(
    state: Dict[Text, Any], candidates: List[Dict[Text, Any]], service_unavailable: bool, problems: List[Dict[Text, Any]]
) -> None:
    state["waiting_for"] = "priority_choice"


def _is_locked_on_template(state: Dict[Text, Any], candidates: List[Dict[Text, Any]]) -> bool:
    return bool(state.get("template_id"))


def _continue_locked_template(
    state: Dict[Text, Any], candidates: List[Dict[Text, Any]], service_unavailable: bool, problems: List[Dict[Text, Any]]
) -> None:
    # Diagnostic deja verrouille sur un (service, probleme) resolu a un tour
    # precedent : on continue de collecter ses champs sans se laisser
    # distraire si le message courant ne matche plus aucun mot-cle
    # (l'utilisateur repond a la question posee, il ne relance pas une
    # nouvelle classification).
    if state.get("no_capability_matched"):
        # Deja decide par l'extraction de ce meme tour (voir
        # _extract_field_answer, cas "plus aucun champ de repli
        # disponible") : ne pas recalculer waiting_for ici, ce qui
        # redeviendrait un vrai nom de champ et masquerait cette decision
        # d'escalade prise juste avant dans le meme tour.
        return
    confirmed = state.get("confirmed", {})
    _capture_opportunistic_field_patterns(state, confirmed, state.get("message") or "")
    state["waiting_for"] = _next_step(
        state["required_fields"], confirmed, state.get("diagnostic_confirmed", False)
    )


def _no_candidates(state: Dict[Text, Any], candidates: List[Dict[Text, Any]]) -> bool:
    return not candidates


def _mark_no_capability_matched(
    state: Dict[Text, Any], candidates: List[Dict[Text, Any]], service_unavailable: bool, problems: List[Dict[Text, Any]]
) -> None:
    # Aucune capacite reconnue. Avant de renoncer completement (description
    # libre + ticket), on tente UN niveau de repli : si plusieurs services
    # distincts existent dans le manifeste, on demande a l'utilisateur de
    # preciser lequel, puis on retente le matching restreint a ce service sur
    # le MEME message original (voir _extract_service_narrowing). Avec un
    # seul service au catalogue (cas actuel), il n'y a rien a departager --
    # on saute directement a la description libre, une question "c'est
    # Wallet ou Wallet ?" n'aurait aucun sens.
    #
    # Regle metier (ne jamais proposer un ticket comme simple consequence
    # d'un double echec de classification, voir _respond_no_capability_matched) :
    # `no_capability_matched_reason` retient POURQUOI on abandonne, pour que
    # le message final explique une vraie raison plutot qu'un texte fixe.
    #
    # Exception : si l'utilisateur signale lui-meme que le probleme persiste
    # (voir _looks_like_persistent_complaint) sur CE tour, il a deja
    # implicitement essaye -- lui reposer la question "quel service ?" serait
    # perçu comme ignorer ce qu'il vient de dire. On saute directement a la
    # proposition de ticket, avec une raison dediee.
    if not service_unavailable and state.get("_persistence_signal_this_turn"):
        state["no_capability_matched"] = True
        state["service_unavailable"] = False
        state["no_capability_matched_reason"] = "user_reported_persistence"
        state["waiting_for"] = ""
        return

    services = _known_services(problems)
    if len(services) > 1 and not state.get("narrowing_attempted"):
        state["known_services"] = services
        state["waiting_for"] = "service_narrowing"
        return

    state["no_capability_matched"] = True
    state["service_unavailable"] = service_unavailable
    state["no_capability_matched_reason"] = (
        "narrowing_failed" if state.get("narrowing_attempted") else "description_failed"
    )
    state["waiting_for"] = "" if state.get("confirmed", {}).get("description") else "description"


def _has_single_clear_winner(state: Dict[Text, Any], candidates: List[Dict[Text, Any]]) -> bool:
    # Un simple `>` laissait n'importe quel ecart, meme du bruit de mesure
    # (voir CLASSIFICATION_RELATIVE_MARGIN), verrouiller le mauvais probleme.
    # Si l'ecart n'est pas net, _mark_pending_choices (dernier recours de
    # CLASSIFICATION_RULES) prend le relais et demande explicitement a
    # l'utilisateur de choisir, au lieu de deviner.
    return _has_meaningful_margin(candidates, CLASSIFICATION_RELATIVE_MARGIN)


def _lock_new_template(
    state: Dict[Text, Any], candidates: List[Dict[Text, Any]], service_unavailable: bool, problems: List[Dict[Text, Any]]
) -> None:
    best = candidates[0]
    state["service_id"] = best["service_id"]
    state["template_id"] = best["problem_id"]
    state["template_name"] = best["label"]
    state["required_fields"] = best["required_fields"]
    state["optional_fields"] = best["optional_fields"]
    state["fallback_fields"] = best.get("fallback_fields", [])
    state["field_specs"] = best["field_specs"]
    # Meme raisonnement que le reset de _multi_problem_detected (voir
    # ActionRunDiagnosticStep) : sans ce reset explicite, un
    # no_capability_matched pose Vrai a un tour precedent (ex. l'utilisateur
    # ne donne d'abord que le nom du service, "user", sans decrire son
    # probleme) restait fige a True indefiniment, y compris apres ce
    # verrouillage reussi sur un vrai probleme. _respond_engine_outcome
    # n'etait alors jamais atteint au tour de confirmation suivant (voir
    # ActionRunDiagnosticStep) : le moteur de diagnostic n'etait jamais
    # appele, donc jamais le vrai statut (ex. KYC) en base cote
    # wallet/user-service -- seul un message d'escalade generique
    # s'affichait, a tort.
    state["no_capability_matched"] = False
    # Meme bug potentiel que no_capability_matched ci-dessus, pour
    # narrowing_attempted (pose par _extract_service_narrowing) : sans ce
    # reset, un echec de narrowing sur un SUJET donne bloquait silencieusement
    # la question "quel service ?" pour un echec ulterieur SANS RAPPORT, dans
    # la meme conversation diagnostic_state encore ouverte.
    state["narrowing_attempted"] = False
    # Le message qui vient d'etre classe peut deja contenir la reponse a un
    # champ requis (ex. la reference donnee dans la meme phrase que la
    # description du probleme) : sans cette capture, le bot la redemandait
    # inutilement juste apres l'avoir verrouille sur ce probleme.
    confirmed = state.get("confirmed", {})
    _capture_opportunistic_field_patterns(state, confirmed, state.get("message") or "")
    _capture_opportunistic_nlu_entities(state, confirmed, state.get("message_entities") or [])
    state["waiting_for"] = _next_step(
        state["required_fields"], confirmed, state.get("diagnostic_confirmed", False)
    )


def _mark_pending_choices(
    state: Dict[Text, Any], candidates: List[Dict[Text, Any]], service_unavailable: bool, problems: List[Dict[Text, Any]]
) -> None:
    # Dernier recours (aucune des conditions precedentes n'a matche) :
    # plusieurs candidats a egalite, aucun gagnant clair.
    state["pending_choices"] = candidates
    state["waiting_for"] = "priority_choice"


# (condition, action) : la premiere condition vraie l'emporte. `None` comme
# condition = executee seulement si aucune regle precedente n'a matche
# (equivalent du `else` final).
CLASSIFICATION_RULES: List[
    tuple[Callable[[Dict[Text, Any], List[Dict[Text, Any]]], bool] | None, Callable[..., None]]
] = [
    (_has_pending_choices, _lock_priority_choice),
    (_is_locked_on_template, _continue_locked_template),
    (_no_candidates, _mark_no_capability_matched),
    (_has_multiple_distinct_problems, _mark_pending_choices),
    (_has_single_clear_winner, _lock_new_template),
    (None, _mark_pending_choices),
]


def _run_classification_rules(
    state: Dict[Text, Any], candidates: List[Dict[Text, Any]], service_unavailable: bool, problems: List[Dict[Text, Any]]
) -> None:
    for condition, action in CLASSIFICATION_RULES:
        if condition is None or condition(state, candidates):
            action(state, candidates, service_unavailable, problems)
            return


# --- Question suivante ou resolution (ex action_next_diagnostic_question) :
# meme principe de dispatch par dictionnaire que EXTRACTION_HANDLERS.

def _respond_priority_choice(
    state: Dict[Text, Any], dispatcher: CollectingDispatcher, tracker: Tracker, state_events, reset_events
) -> List[Dict[Text, Any]]:
    choices = state.get("pending_choices", [])
    choice_labels = [choice["label"] for choice in choices]
    dispatcher.utter_message(
        text=(
            "Vous semblez signaler plusieurs problèmes : "
            f"{', '.join(choice_labels)}. Lequel souhaitez-vous traiter en priorité ? "
            "(répondez par son nom ou son numéro)"
        )
    )
    return state_events


def _respond_diagnostic_confirmation(
    state: Dict[Text, Any], dispatcher: CollectingDispatcher, tracker: Tracker, state_events, reset_events
) -> List[Dict[Text, Any]]:
    confirmed = state.get("confirmed", {})
    template_name = state.get("template_name", "")
    if confirmed:
        recap = ", ".join(f"{FIELD_LABELS.get(key, key)} : {value}" for key, value in confirmed.items())
        text = f"Récapitulatif — {template_name} : {recap}. Je lance la vérification, c'est bien ça ? (oui/non)"
    else:
        # Aucun champ a recapituler (cas des problemes resolubles a partir du
        # seul user_id, ex. KYC) : "aucune information supplementaire"
        # sonnait comme un recapitulatif rate plutot qu'une simple question.
        text = f"Je vais vérifier votre dossier concernant : {template_name}. C'est bien ça ? (oui/non)"
    dispatcher.utter_message(text=text)
    return state_events


def _respond_service_narrowing(
    state: Dict[Text, Any], dispatcher: CollectingDispatcher, tracker: Tracker, state_events, reset_events
) -> List[Dict[Text, Any]]:
    services = state.get("known_services", [])
    labels = [_service_label(service) for service in services]
    dispatcher.utter_message(
        text=(
            "Je n'arrive pas à identifier précisément votre problème. "
            f"Est-ce plutôt lié à {_join_or(labels)} ?"
        )
    )
    return state_events


RESPONSE_HANDLERS: Dict[
    Text, Callable[[Dict[Text, Any], CollectingDispatcher, Tracker, Any, Any], List[Dict[Text, Any]]]
] = {
    "priority_choice": _respond_priority_choice,
    "diagnostic_confirmation": _respond_diagnostic_confirmation,
    "service_narrowing": _respond_service_narrowing,
}


def _respond_field_question(
    state: Dict[Text, Any],
    dispatcher: CollectingDispatcher,
    tracker: Tracker,
    state_events,
    pending_field: Text,
) -> List[Dict[Text, Any]]:
    # Handler par defaut : n'importe quel nom de champ metier (impossible a
    # enumerer a l'avance, vient du manifeste dynamique).
    spec = (state.get("field_specs") or {}).get(pending_field, {})
    question = _field_question(pending_field, spec.get("description") or "Pouvez-vous préciser ce point ?")
    if state.get("invalid_field_attempt") == pending_field:
        question = f"Ce format ne semble pas correct. {question}"
    dispatcher.utter_message(text=question)
    return state_events


def _respond_no_capability_matched(
    state: Dict[Text, Any], dispatcher: CollectingDispatcher, tracker: Tracker, reset_events
) -> List[Dict[Text, Any]]:
    # Regle 6 : expliquer POURQUOI un ticket est propose, jamais un texte fixe
    # qui ne justifie rien -- la raison vient de no_capability_matched_reason,
    # posee par _mark_no_capability_matched.
    description = state.get("confirmed", {}).get("description") or tracker.latest_message.get("text") or ""
    reason = state.get("no_capability_matched_reason")

    if state.get("service_unavailable"):
        message = "Ce service est indisponible pour le moment. Voulez-vous que je crée un ticket de réclamation directement ?"
    elif reason == "user_reported_persistence":
        message = (
            "Vous indiquez que ce problème persiste malgré vos tentatives précédentes. "
            "Je n'ai pas pu le rattacher automatiquement à l'un de nos diagnostics à partir de votre message, "
            "mais pour ne pas vous faire attendre davantage, je vous propose de créer un ticket afin qu'un "
            "membre de notre équipe technique le prenne en charge directement. Voulez-vous que je le crée ?"
        )
    elif reason == "narrowing_failed":
        message = (
            "Je n'ai pas réussi à déterminer précisément quel service est concerné par votre demande, "
            "même après vous avoir demandé de préciser. Je vous propose de créer un ticket afin qu'un membre "
            "de notre équipe technique examine votre cas directement. Voulez-vous que je le crée ?"
        )
    elif reason == "fields_unavailable":
        # L'utilisateur a indique ne pas pouvoir fournir ni le champ requis
        # ni son repli (cannot_provide_field detecte deux fois de suite --
        # voir _handle_cannot_provide_field). Contrairement aux branches
        # ci-dessus, pas d'echec de classification ici : le probleme EST
        # identifie, seules les informations necessaires pour le verifier
        # manquent reellement.
        message = (
            "Je ne peux pas continuer le diagnostic sans ces informations. "
            "Je transmets votre demande à notre équipe technique. Voulez-vous que je crée un ticket de réclamation ?"
        )
    else:
        # "description_failed" ou raison absente (filet de securite) : repli
        # generique classique.
        message = (
            "Je n'ai pas réussi à rattacher votre description à l'un de nos diagnostics automatiques. "
            "Je vous propose de créer un ticket afin qu'un membre de notre équipe technique s'en occupe "
            "directement. Voulez-vous que je le crée ?"
        )
        if state.get("_user_reported_persistence"):
            message = "Comme vous l'indiquez, " + message[0].lower() + message[1:]

    dispatcher.utter_message(text=message)
    return reset_events + [
        {"event": "slot", "name": "category", "value": "Diagnostic"},
        {"event": "slot", "name": "description", "value": description},
        {"event": "slot", "name": "urgency", "value": "medium"},
        # ActionCreateTicket (reclamation.py) rejette tout ticket sans
        # summary non vide (FastAPI ComplaintService.create_ticket leve
        # ValueError sinon) -- ce slot n'est normalement rempli que par
        # action_generate_reclamation_summary (flux formulaire classique),
        # jamais atteinte sur ce chemin d'escalade diagnostic. Sans cette
        # ligne, toute confirmation "oui" echouait ici de facon identique et
        # repetee (constate en pratique : "le service est momentanement
        # indisponible" a chaque nouvelle tentative, alors que la vraie cause
        # etait un resume manquant, pas une panne reseau).
        {"event": "slot", "name": "summary", "value": f"[Diagnostic] {description or 'Aucune capacité correspondante identifiée.'}"},
        {"event": "slot", "name": "claim_requested", "value": True},
        {"event": "slot", "name": "ticket_source", "value": "user_diagnostic_escalation"},
    ]


def _respond_engine_outcome(
    state: Dict[Text, Any],
    dispatcher: CollectingDispatcher,
    tracker: Tracker,
    state_events,
    reset_events,
) -> List[Dict[Text, Any]]:
    result = _call_diagnostic_engine(tracker, state)
    outcome = result.get("outcome") if result else None

    if outcome == "RESOLVED":
        # Mode Super-Agent (2026-07-30, voir is_superagent_mode) : un dossier
        # KYC en cours d'examen est normalement une simple INFORMATION pour
        # l'agent standard (l'utilisateur attend, aucune action n'est prise).
        # Le Super-Agent, lui, a l'autorisation d'agir directement plutot que
        # de faire attendre -- c'est precisement la difference entre les deux
        # paliers d'agent (voir la strategie de soutenance) : meme situation,
        # decision differente selon le niveau de risque assume.
        if (
            is_superagent_mode(tracker)
            and state.get("service_id") == "user"
            and result.get("resolution_code") == "KYC_UNDER_REVIEW"
        ):
            _report_agent_action(
                session_id=tracker.sender_id,
                domain="diagnostic_superagent",
                action_type="kyc_fast_tracked",
                input_data={"service_id": "user", "problem_id": state.get("template_id")},
                output_data={"resolution_code": "KYC_UNDER_REVIEW", "decision": "fast_tracked"},
            )
            dispatcher.utter_message(
                text="🔓 Mode Super-Agent : plutôt que de vous laisser attendre l'examen standard, "
                "j'ai directement priorisé votre dossier de vérification d'identité. Cette décision "
                "a été tracée et reste soumise à un contrôle a posteriori de notre équipe conformité."
            )
            return reset_events

        dispatcher.utter_message(text=result.get("message", "Votre problème a été résolu."))
        # Le message ci-dessus vient du moteur de diagnostic (contenu
        # dynamique, jamais reformule ici) et n'invite jamais lui-meme a
        # continuer -- message separe, avec ses propres variantes, pour ne
        # pas repeter la meme relance a chaque resolution.
        dispatcher.utter_message(
            text=pick(
                "Puis-je vous aider sur autre chose ?",
                "Y a-t-il autre chose que je peux faire pour vous ?",
                "N'hésitez pas si vous avez une autre question.",
            ),
            buttons=QUICK_ACTION_BUTTONS,
        )
        return reset_events

    if outcome == "NEED_MORE_INFO":
        missing = ", ".join(FIELD_LABELS.get(field, field) for field in result.get("missing_fields", []))
        dispatcher.utter_message(text=f"J’ai encore besoin de : {missing}.")
        return state_events

    if outcome == "_ENGINE_UNAVAILABLE":
        # Panne technique (timeout/erreur reseau/5xx, deja retentee par
        # request_with_retry) : a distinguer d'une vraie decision ESCALATE
        # du moteur (audit robustesse UX). Ne propose PAS de ticket des la
        # 1ere panne -- seulement si la MEME panne se reproduit au tour
        # suivant (compteur conserve dans diagnostic_state, jamais reset
        # tant que le moteur ne repond pas avec succes).
        attempts = state.get("_engine_unavailable_count", 0) + 1
        state["_engine_unavailable_count"] = attempts
        if attempts < ENGINE_UNAVAILABLE_ESCALATION_THRESHOLD:
            kind = result.get("kind")
            dispatcher.utter_message(
                text=ENGINE_UNAVAILABLE_MESSAGES.get(kind, ENGINE_UNAVAILABLE_MESSAGES["http_error"])
            )
            # diagnostic_state reconstruit ICI (pas `state_events`, deja
            # serialise par l'appelant AVANT cet appel, donc sans le
            # compteur qu'on vient d'incrementer) : conserve le necessaire
            # pour qu'un prochain message de l'utilisateur rejoue ce meme
            # chemin sans rien redemander.
            return [
                {"event": "slot", "name": "pending_field", "value": None},
                {"event": "slot", "name": "diagnostic_state", "value": json.dumps(state, ensure_ascii=False)},
            ]
        message = (
            "Je rencontre toujours une difficulté technique pour accéder à votre dossier. "
            "Je transmets votre demande à notre équipe technique."
        )
        category = state.get("service_id", "Diagnostic")
        urgency = "medium"
    elif outcome == "ESCALATE":
        # Mode Super-Agent (2026-07-30, voir le hook symetrique sur RESOLVED
        # ci-dessus pour le KYC) : un retrait bloque au-dela du SLA est
        # normalement escalade vers un ticket humain (voir
        # PENDING_BEYOND_SLA_NO_PROVIDER_RESPONSE, wallet_stub/diagnostic/
        # services/withdrawal.py) -- l'agent standard n'a pas l'autorite de
        # trancher seul sans reponse du prestataire de paiement. Le
        # Super-Agent, lui, assume le risque d'un remboursement direct plutot
        # que de faire attendre l'utilisateur : action volontairement
        # RISQUEE (double remboursement possible si le prestataire finit par
        # repondre positivement) -- exactement le type de decision qu'un
        # agent standard ne doit jamais prendre seul, tracee ici pour rester
        # auditable.
        if (
            is_superagent_mode(tracker)
            and state.get("service_id") == "wallet"
            and result.get("escalation_reason") == "PENDING_BEYOND_SLA_NO_PROVIDER_RESPONSE"
        ):
            _report_agent_action(
                session_id=tracker.sender_id,
                domain="diagnostic_superagent",
                action_type="withdrawal_force_refunded",
                input_data={"service_id": "wallet", "problem_id": state.get("template_id"),
                            "entities": _entities_for_engine(state.get("confirmed") or {})},
                output_data={"escalation_reason": "PENDING_BEYOND_SLA_NO_PROVIDER_RESPONSE", "decision": "force_refunded"},
            )
            dispatcher.utter_message(
                text="🔓 Mode Super-Agent : votre retrait dépasse le délai normal sans réponse du "
                "prestataire de paiement. Plutôt que d'attendre davantage, j'ai directement déclenché "
                "le remboursement sur votre portefeuille NGONI. Cette décision a été tracée et reste "
                "soumise à un contrôle a posteriori de notre équipe technique."
            )
            return reset_events

        message = result.get("message", "Je transmets votre demande à notre équipe.")
        escalation = result.get("escalation_payload", {})
        category = escalation.get("category", state.get("service_id", "Diagnostic"))
        urgency = escalation.get("urgency", "medium")
    else:
        message = "Je transmets votre demande à notre équipe technique."
        category = state.get("service_id", "Diagnostic")
        urgency = "medium"

    description = f"Diagnostic {state.get('template_name', '')} : " + ", ".join(
        f"{k}={v}" for k, v in state.get("confirmed", {}).items()
    )
    # Cas 11 : reference l'avertissement conditionnel de l'utilisateur s'il y
    # en a eu un ("si ça continue je veux faire une réclamation") -- la
    # reclamation proposee ici n'est alors plus une surprise, mais la suite
    # logique de ce qu'il avait annonce.
    if state.get("_escalation_warned"):
        message = "Comme vous l'aviez indiqué, " + message[0].lower() + message[1:]
    dispatcher.utter_message(text=f"{message} Voulez-vous que je crée un ticket de réclamation ?")
    # escalation_recheck_context (audit "robustesse comportementale", cas 40) :
    # preserve le strict necessaire (service/probleme/champs confirmes) pour
    # qu'ActionCreateTicket (reclamation.py) puisse reinterroger le moteur
    # UNE derniere fois juste avant de creer le ticket. Sans ca, reset_events
    # vide deja diagnostic_state ici meme -- si le probleme se resout entre
    # cette proposition d'escalade et le "oui" de confirmation (ex. un
    # retrait qui passe de pending a completed pendant que l'utilisateur lit
    # le message), rien ne permettait de le detecter : le ticket etait cree
    # inconditionnellement pour un probleme deja resolu.
    return reset_events + [
        {"event": "slot", "name": "category", "value": category},
        {"event": "slot", "name": "description", "value": description},
        {"event": "slot", "name": "urgency", "value": urgency},
        # Voir le commentaire equivalent dans _respond_no_capability_matched
        # ci-dessus : sans ce slot, ActionCreateTicket (reclamation.py) echoue
        # systematiquement (resume vide rejete par FastAPI) sur CE chemin
        # d'escalade precis, avec un message trompeur ("service indisponible")
        # qui masque la vraie cause.
        {"event": "slot", "name": "summary", "value": f"[Diagnostic] {description}"},
        {"event": "slot", "name": "claim_requested", "value": True},
        {"event": "slot", "name": "ticket_source", "value": "user_diagnostic_escalation"},
        {
            "event": "slot",
            "name": "escalation_recheck_context",
            "value": json.dumps(
                {
                    "service_id": state.get("service_id"),
                    "template_id": state.get("template_id"),
                    "confirmed": state.get("confirmed", {}),
                },
                ensure_ascii=False,
            ),
        },
    ]


# --- Detection d'un changement de sujet pendant un diagnostic en cours
# (waiting_for actif sur un probleme deja verrouille) : plutot que de
# compter les tours ecoules depuis la derniere interaction diagnostic
# (fragile -- depend de qui a traite les messages intermediaires), on se
# base sur le contenu, en deux temps :
#   1) l'extraction du champ attendu est tentee EN PREMIER (voir
#      ActionRunDiagnosticStep.run()) -- si elle reussit avec une preuve
#      fiable (_extraction_confidently_succeeded), on lui fait confiance et
#      on continue normalement, meme si le message score aussi bien sur un
#      autre probleme (une reponse peut ressembler a la fois a une reponse
#      valide ET a un nouveau sujet, ex. "je n'arrive plus a me connecter"
#      en reponse a une question de description) ;
#   2) seulement si l'extraction n'apporte PAS de preuve fiable (cas des
#      champs libres sans pattern de validation, ou d'un choix qui n'a
#      matche aucune option), on regarde si le message correspond, de
#      maniere nette, a un probleme different de celui deja verrouille.

def _extraction_confidently_succeeded(state: Dict[Text, Any], waiting_for: Text) -> bool:
    if waiting_for == "diagnostic_confirmation":
        # Question fermee (oui/non) : l'intention affirm/deny (ou
        # NEGATION_PATTERN en repli) est fiable sur une reponse courte de ce
        # type -- voir _extract_diagnostic_confirmation.
        return True
    if waiting_for in ("priority_choice", "service_narrowing"):
        return state.get("chosen_candidate") is not None
    pattern = (state.get("field_specs") or {}).get(waiting_for, {}).get("pattern")
    if not pattern:
        # Champ libre (ex. description, amount, date...) : _extract_field_answer
        # capture toujours la reponse verbatim faute de contrainte de format,
        # ce qui ne prouve pas qu'elle concerne bien le diagnostic en cours.
        return False
    return state.get("invalid_field_attempt") != waiting_for


def _has_meaningful_margin(candidates: List[Dict[Text, Any]], threshold: float) -> bool:
    """Le 1er candidat est-il assez nettement en tete du 2e pour qu'on lui
    fasse confiance ? `threshold` differe selon l'appelant : verrouiller un
    nouveau probleme tolere un ecart plus faible (CLASSIFICATION_RELATIVE_MARGIN)
    qu'interrompre un diagnostic deja en cours (TOPIC_SWITCH_RELATIVE_MARGIN,
    plus strict -- voir les deux constantes)."""
    if len(candidates) < 2:
        return True
    best, second = candidates[0], candidates[1]
    if best["confidence"] <= 0:
        return False
    relative_gap = (best["confidence"] - second["confidence"]) / best["confidence"]
    return relative_gap >= threshold


def _looks_like_new_topic(
    previous_state: Dict[Text, Any], candidates: List[Dict[Text, Any]]
) -> Dict[Text, Any] | None:
    if not candidates:
        return None
    best = candidates[0]
    if (best["service_id"], best["problem_id"]) == (
        previous_state.get("service_id"),
        previous_state.get("template_id"),
    ):
        return None
    if not _has_meaningful_margin(candidates, TOPIC_SWITCH_RELATIVE_MARGIN):
        return None
    return best


def _describe_pending_question(state: Dict[Text, Any]) -> Text:
    pending = state.get("waiting_for")
    if pending == "priority_choice":
        return "lequel de ces problèmes traiter en priorité"
    if pending == "diagnostic_confirmation":
        return "si je pouvais lancer la vérification"
    if pending == "service_narrowing":
        return "à quel service se rapporte votre problème"
    spec = (state.get("field_specs") or {}).get(pending, {})
    return _field_question_canonical(pending) or spec.get("description") or "une précision sur votre problème"


def _suspend_for_topic_switch(
    previous_state: Dict[Text, Any],
    dispatcher: CollectingDispatcher,
    tracker: Tracker,
) -> List[Dict[Text, Any]]:
    # Copie profonde (pas une liste figee de cles) : un futur champ ajoute a
    # `state` (ex. priority_level) est suspendu/restaure automatiquement,
    # sans avoir a mettre cette fonction a jour en meme temps.
    suspended = copy.deepcopy(previous_state)
    new_state = {
        "waiting_for": "resume_or_new_topic",
        "confirmed": {},
        "_suspended": suspended,
        "_new_topic_message": tracker.latest_message.get("text") or "",
        "_previous_template": suspended.get("template_name") or suspended.get("service_id") or "votre demande précédente",
        "_previous_question": _describe_pending_question(suspended),
        "_interrupted_at": time.time(),
    }
    dispatcher.utter_message(
        text=(
            f"Avant votre dernier message, nous étions en train de traiter « {new_state['_previous_template']} » "
            f"et j’attendais : {new_state['_previous_question']}. "
            "Voulez-vous reprendre ce diagnostic (oui), ou votre message concerne-t-il autre chose (non) ?"
        )
    )
    return [
        {"event": "slot", "name": "pending_field", "value": "resume_or_new_topic"},
        {"event": "slot", "name": "diagnostic_state", "value": json.dumps(new_state, ensure_ascii=False)},
    ]


def _resolve_topic_switch_resume(
    state: Dict[Text, Any], dispatcher: CollectingDispatcher, tracker: Tracker
) -> List[Dict[Text, Any]]:
    suspended = state.get("_suspended") or {}
    pending_field = suspended.get("waiting_for") or None
    state_events = [
        {"event": "slot", "name": "pending_field", "value": pending_field},
        {"event": "slot", "name": "diagnostic_state", "value": json.dumps(suspended, ensure_ascii=False)},
    ]
    reset_events = [
        {"event": "slot", "name": "diagnostic_state", "value": "{}"},
        {"event": "slot", "name": "pending_field", "value": None},
    ]
    dispatcher.utter_message(text="D’accord, on reprend là où nous en étions.")
    if pending_field in RESPONSE_HANDLERS:
        return RESPONSE_HANDLERS[pending_field](suspended, dispatcher, tracker, state_events, reset_events)
    if pending_field:
        return _respond_field_question(suspended, dispatcher, tracker, state_events, pending_field)
    # Ne devrait pas arriver (on ne suspend que si un waiting_for etait actif
    # au moment de la detection) : filet de securite, on restaure l'etat
    # plutot que de planter sur un cas impossible en theorie.
    return state_events


# --- Cloture spontanee (audit "robustesse comportementale", cas 29/30/37) :
# un utilisateur peut annoncer en cours de diagnostic que son probleme s'est
# resolu tout seul ("ça y est mon retrait vient d'arriver"). Deliberement PAS
# un nouvel intent NLU : nlu.yml contient deja, dans les exemples de deny,
# des formulations tres proches ("Non, mon problème est déjà résolu.", "non
# c bon j'ai résolu tou seul") -- un intent separe avec un vocabulaire aussi
# proche aurait exactement reproduit l'incident deja rencontre cette session
# sur modify_reclamation/confirm_full_cancel (le nouvel intent "aspirait" les
# exemples de deny a l'entrainement, deregleant la classification de "non"
# lui-meme). Detection par mots-cles sur des LOCUTIONS completes (pas des
# mots isoles) : "c'est résolu" ne matche jamais "n'est pas résolu" ou
# "toujours pas résolu" puisque ce ne sont pas la meme sous-chaine.
_RESOLUTION_PHRASES = (
    "c'est bon", "c est bon",
    "c'est réglé", "c'est regle", "c est réglé", "c est regle",
    "c'est résolu", "c'est resolu", "c est résolu", "c est resolu",
    "ça marche maintenant", "ca marche maintenant",
    "ça a fonctionné", "ca a fonctionne",
    "ça fonctionne maintenant", "ca fonctionne maintenant",
    "ça y est", "ca y est",
    "c'est arrivé", "c'est arrive", "c est arrivé", "c est arrive",
    "je l'ai reçu", "je l ai reçu", "je l'ai recu", "je l ai recu",
    "vient d'arriver", "vient d arriver",
    "tout est rentré dans l'ordre", "tout est rentre dans l ordre",
    "problème résolu", "probleme resolu",
    "plus besoin", "plus la peine",
    # Ajouts suite a la grande vague de tests conversationnels (2026-07) :
    # verbes de resolution SANS negation grammaticale (donc invisibles a
    # NEGATION_PATTERN/_RESOLVED_STATE_PATTERN) -- "a ete leve"/"a ete
    # recupere"/"a fini par etre valide" annoncent une resolution tout
    # autant que "n'est plus bloque", juste par un autre verbe.
    "a été levé", "a ete leve", "a été levée", "a ete levee",
    "a été récupéré", "a ete recupere", "a été récupérée", "a ete recuperee",
    "bien été récupéré", "bien ete recupere", "bien été récupérée", "bien ete recuperee",
    "a fini par être validé", "a fini par etre valide",
    "a fini par être validée", "a fini par etre validee",
    "a été débloqué", "a ete debloque", "a été débloquée", "a ete debloquee",
)

# Audit qualite du code, cas #2 : meme evaluation embedding-vs-mots-cles que
# _looks_like_refusal/_looks_like_uncertain plus bas, meme verdict --
# mesure sur cette liste : "ca fait depuis ce matin" (une vraie reponse de
# diagnostic, sans rapport avec une resolution) score 0.8911 de similarite
# au meilleur exemple de resolution, PLUS HAUT que "ok super merci ça a
# fonctionne" (vraie resolution) a 0.8518. Un faux positif ici clorait un
# diagnostic encore en cours sur la seule foi d'une reponse ordinaire --
# reste phrase-list pour la meme raison (voir le detail complet plus bas).


def _looks_like_resolution(text: Text) -> bool:
    return any(phrase in text for phrase in _RESOLUTION_PHRASES)


# --- Avertissement conditionnel d'escalade (audit "robustesse
# comportementale", cas 11 : "Mon retrait est bloqué. Si ça continue je veux
# faire une réclamation."). Pas de routage special -- le diagnostic
# continue normalement -- seulement une memorisation de l'intention pour
# que, SI le diagnostic echoue reellement, le message d'escalade
# (_respond_engine_outcome) puisse la referencer au lieu de creer une
# reclamation qui semble sortie de nulle part.
# Audit qualite du code, cas #2 : meme reserve que _looks_like_resolution
# plus bas -- pas re-mesure separement ici (enjeu different, purement une
# note memorisee pour un message ulterieur, pas une perte d'information),
# mais rien ne garantit un seuil plus fiable sur ce meme modele.
_CONDITIONAL_ESCALATION_PHRASES = (
    "si ça continue", "si ca continue",
    "si ça persiste", "si ca persiste",
    "sinon je vais", "sinon j'irai", "sinon j irai",
    "sinon je porterai plainte", "sinon je ferai une réclamation", "sinon je ferai une reclamation",
)


def _looks_like_conditional_escalation_warning(text: Text) -> bool:
    return any(phrase in text for phrase in _CONDITIONAL_ESCALATION_PHRASES)


# Regle 5 (4e cas) : l'utilisateur indique que le probleme PERSISTE DEJA
# (pas une menace conditionnelle future -- voir _CONDITIONAL_ESCALATION_PHRASES
# ci-dessus, "si ça persiste" reste dans cette liste-la, volontairement absent
# d'ici pour ne pas confondre les deux). Utilise par _mark_no_capability_matched
# pour proposer un ticket sans repasser par narrowing/description quand
# l'utilisateur a deja implicitement essaye.
_PERSISTENT_COMPLAINT_PHRASES = (
    "toujours pas résolu", "toujours pas resolu",
    "toujours pas réglé", "toujours pas regle",
    "depuis plusieurs jours", "depuis des jours", "depuis plusieurs semaines",
    "j'ai déjà essayé plusieurs fois", "jai deja essaye plusieurs fois",
    "malgré plusieurs tentatives", "malgre plusieurs tentatives",
    "rien ne fonctionne malgré", "rien ne fonctionne malgre",
)


def _looks_like_persistent_complaint(text: Text) -> bool:
    return any(phrase in text for phrase in _PERSISTENT_COMPLAINT_PHRASES)


# --- Refus de repondre et reponses vagues (audit "robustesse
# comportementale", cas 7 et 31) : meme constat que _RESOLUTION_PHRASES,
# locutions completes plutot que mots isoles pour eviter les faux positifs
# ("je ne sais pas si c'est bloque" ne doit pas se confondre avec "je ne
# sais pas la reference"). Les deux listes restent separees (messages de
# suite differents : un refus ferme la question, une incertitude propose de
# continuer sans) mais partagent le meme point d'integration
# (_extract_field_answer) : dans les deux cas, la reponse n'est PAS une
# valeur exploitable pour le champ attendu, et redemander mecaniquement la
# meme question boucle sans jamais avancer.
#
# Audit qualite du code, cas #2 : passage a l'embedding EVALUE puis REJETE
# apres mesure (meme methodologie que le benchmark numpy de
# _score_capabilities_embeddings, cas #3) -- contrairement a
# platform/device/error_type (cas #1, voir reclamation.py) ou un seuil
# absolu de 0.90 separait proprement signal reel et hors-sujet, ces
# detecteurs-ci n'ont PAS de seuil sur qui separe correctement les deux
# groupes : le cout d'un faux positif est aussi asymetrique (perdre une
# vraie reponse de diagnostic vs. mal-etiqueter une metadonnee de ticket).
# Mesure sur 8 vraies reponses de diagnostic vs. 6 vrais refus/incertitudes
# (similarite max au meilleur exemple de la categorie testee) :
#   Vrais refus/incertains : 0.9440 / 0.8656 / 0.9159 / 0.9588 / 0.9250 / 0.8756
#   Reponses reelles (bruit): 0.8832 / 0.8802 / 0.8629 / 0.8433 / 0.8441 / 0.8113 / 0.8296 / 0.8277
# Chevauchement direct : "ecoute ça reste prive desole" (vrai refus) score
# 0.8656, EN DESSOUS de "aucun message d'erreur juste rien ne se passe"
# (vraie reponse de diagnostic) a 0.8802 sur ce meme axe -- aucun seuil ne
# peut les separer sans perdre l'un ou l'autre. Contrairement au repli
# mots-cles (filet de securite en cas d'echec reseau, cf. _fetch_capabilities
# vs. keywords), une confusion ICI ferait perdre silencieusement une
# information de diagnostic reelle -- pire que le faux negatif occasionnel
# du phrase-list actuel (qui ne rate qu'une formulation absente de la liste,
# jamais une vraie reponse). Reste donc phrase-list, par choix documente et
# mesure, pas par defaut.
_REFUSAL_PHRASES = (
    "je ne veux pas répondre", "je ne veux pas repondre",
    "je préfère ne pas dire", "je prefere ne pas dire",
    "je préfère ne pas répondre", "je prefere ne pas repondre",
    "je ne dirai pas", "je ne souhaite pas répondre", "je ne souhaite pas repondre",
    "c'est privé", "c est prive", "c'est confidentiel", "c est confidentiel",
    "ça ne vous regarde pas", "ca ne vous regarde pas",
)

_UNCERTAINTY_PHRASES = (
    "je sais pas", "je ne sais pas", "aucune idée", "aucune idee",
    "je ne suis pas sûr", "je ne suis pas sur", "pas sûr", "pas sur",
    "je ne me souviens plus", "je ne me rappelle plus",
    "difficile à dire", "difficile a dire",
)

# Distinct de _REFUSAL_PHRASES (refus de repondre) et _UNCERTAINTY_PHRASES
# (incertitude sur une valeur) : ici l'utilisateur affirme ne pas POSSEDER
# l'information demandee (rapport utilisateur, "champs alternatifs") --
# seul ce cas declenche une bascule vers fallback_fields quand ce dernier
# existe (voir _extract_field_answer).
_CANNOT_PROVIDE_FIELD_PHRASES = (
    "je ne l'ai pas", "je ne l ai pas", "je n'ai pas ça", "je n'ai pas ca",
    "je n'ai pas ce numéro", "je n'ai pas ce numero",
    "je n'ai pas cette référence", "je n'ai pas cette reference",
    "je n'ai pas cette information", "je n'ai pas cette info",
    "je ne connais pas la référence", "je ne connais pas la reference",
    "je ne l'ai plus", "je ne l ai plus",
    "je n'ai pas de référence", "je n'ai pas de reference",
)


def _looks_like_refusal(text: Text) -> bool:
    return any(phrase in text for phrase in _REFUSAL_PHRASES)


def _looks_like_uncertain(text: Text) -> bool:
    return any(phrase in text for phrase in _UNCERTAINTY_PHRASES)


def _looks_like_cannot_provide_field(text: Text) -> bool:
    return any(phrase in text for phrase in _CANNOT_PROVIDE_FIELD_PHRASES)


class ActionReaskPendingDiagnosticField(Action):
    """Re-affiche la question de diagnostic en attente, SANS reinterpreter le
    dernier message de l'utilisateur comme une tentative de reponse --
    contrairement a action_run_diagnostic_step, qui retraite toujours
    tracker.latest_message.text (voir son commentaire).

    Audit robustesse (fluidite de la conversation) : les intentions "meta"
    (bot_challenge, ask_capabilities, suggestion, plainte, notation...)
    repondent deja a leur propre question meme en plein diagnostic (voir
    rules.yml, gardees par active_loop: null uniquement), mais laissaient
    ensuite la question de diagnostic en suspens sans jamais la rappeler --
    l'utilisateur devait se souvenir seul de ce qui etait demande. Chainee
    juste apres ces reponses meta (voir rules.yml), cette action se contente
    de relire diagnostic_state/pending_field et de reposer la MEME question,
    via le meme handler que le chemin normal (_respond_field_question) pour
    ne jamais dupliquer sa logique de libelle.

    Ne fait rien (silencieusement) si pending_field est vide ou l'etat
    illisible : ce n'est qu'un rappel best-effort, jamais une etape requise
    du flux.
    """

    def name(self) -> Text:
        return "action_reask_pending_diagnostic_field"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        pending_field = tracker.get_slot("pending_field")
        if not pending_field:
            return []

        raw_state = tracker.get_slot("diagnostic_state") or "{}"
        try:
            state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
            if not isinstance(state, dict):
                raise ValueError("diagnostic_state doit être un objet JSON")
        except (json.JSONDecodeError, ValueError):
            # Meme filet de securite que ActionRunDiagnosticStep : un slot
            # corrompu ne doit jamais faire planter ce simple rappel.
            return []

        _respond_field_question(state, dispatcher, tracker, [], pending_field)
        return []


class ActionRunDiagnosticStep(Action):
    """Consolide en UNE seule action ce qui etait auparavant 4 actions
    chainees par une regle (classify -> extract -> update -> ask/resolve).

    Raison de la fusion : quand 4 actions distinctes sont chainees dans une
    regle, Rasa reevalue TOUTES les policies a CHAQUE etape -- RulePolicy
    n'a pas la priorite garantie jusqu'au bout. Constate en pratique : apres
    2-3 etapes d'une regle, TEDPolicy (entrainee sur les stories, dont
    "diagnostic then escalation to ticket" qui enchaine deux tours complets)
    proposait une prediction concurrente plus confiante et rejouait
    action_classify_service une 2e fois avant la fin de la regle. Une seule
    action = une seule prediction par tour = moins de concurrence possible
    (voir aussi _already_ran_since_last_user_message : filet de securite
    complementaire pour les cas residuels).
    """

    def name(self) -> Text:
        return "action_run_diagnostic_step"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        if _already_ran_since_last_user_message(tracker, self.name()):
            return []

        raw_text = tracker.latest_message.get("text") or ""

        previous_payload = tracker.get_slot("diagnostic_state") or "{}"
        try:
            state = json.loads(previous_payload) if isinstance(previous_payload, str) else previous_payload
            if not isinstance(state, dict):
                raise ValueError("diagnostic_state doit être un objet JSON")
        except (json.JSONDecodeError, ValueError):
            # Filet de securite : un slot corrompu (valeur tronquee, type
            # inattendu) ne doit pas faire planter l'action et bloquer tout le
            # diagnostic -- on repart d'un etat vide plutot que de propager
            # l'exception.
            state = {}
        waiting_for = state.get("waiting_for")

        # Bouton "Lancer un diagnostic" (suggestions d'accueil/relance, voir
        # greeting.py et QUICK_ACTION_BUTTONS dans common.py) : envoie le
        # payload nu /diagnostic, sans description reelle du probleme. Sans ce
        # garde-fou, ce texte (vide ou juste "/diagnostic") descendait
        # directement dans la classification plus bas, qui ne trouve
        # evidemment aucune capacite correspondante a un texte vide et
        # proposait IMMEDIATEMENT la creation d'un ticket
        # (_respond_no_capability_matched) -- avant meme que l'utilisateur
        # n'ait decrit quoi que ce soit. Ne s'applique qu'a une classification
        # fraiche (aucun diagnostic deja en cours, waiting_for et state tous
        # deux vides) : un vrai message utilisateur, meme tres court, ne peut
        # jamais valoir exactement ce payload nu.
        if not waiting_for and not state and raw_text.strip() in ("", "/diagnostic"):
            dispatcher.utter_message(
                text=pick(
                    "Bien sûr. Décrivez-moi le problème que vous rencontrez, je vais essayer de le diagnostiquer.",
                    "D'accord, lançons un diagnostic : quel problème rencontrez-vous exactement ?",
                    "Avec plaisir. Expliquez-moi ce qui ne fonctionne pas, je vais regarder ça avec vous.",
                )
            )
            return []

        if waiting_for == "resume_or_new_topic":
            # Reponse a la question posee par _suspend_for_topic_switch.
            # intent:diagnostic (l'utilisateur redecrit directement un
            # nouveau probleme, sans repondre oui/non) et intent:deny sont
            # traites de la meme facon ; tout le reste (affirm, nlu_fallback,
            # ...) reprend le diagnostic suspendu par defaut -- le choix le
            # moins disruptif quand la reponse est ambigue.
            intent_name = (tracker.latest_message.get("intent") or {}).get("name")
            wants_new_topic = intent_name in ("deny", "diagnostic") or bool(
                NEGATION_PATTERN.search(raw_text.lower())
            )
            if not wants_new_topic:
                return _resolve_topic_switch_resume(state, dispatcher, tracker)
            # Retraitement normal : on repart d'un etat vide et on relance le
            # MEME pipeline ci-dessous (classification -> extraction -> etat
            # -> reponse) sur le message qui avait declenche la detection,
            # exactement comme s'il venait d'etre envoye -- pas de
            # classification/diagnostic "special" duplique ici (voir
            # _suspend_for_topic_switch).
            raw_text = state.get("_new_topic_message") or ""
            state = {}
            waiting_for = None

        # Cause racine du bug "Bonsoir comment allez-vous ? J'ai fait un
        # retrait..." classe comme non exploitable : la classification
        # ci-dessous (_score_capabilities*) travaille par similarite
        # d'embedding sur ce `text`, un preambule de politesse dilue le
        # vecteur moyen et peut faire passer un message pourtant clair sous
        # le seuil de similarite. Retire ce preambule une fois pour toutes ici
        # (voir _strip_greeting_preamble, common.py) plutot que de compter sur
        # la segmentation par ponctuation forte (_segment_message plus bas),
        # qui ne s'applique QUE si l'utilisateur separe la salutation du reste
        # par un ".", "!" ou "?" -- une virgule ou aucune ponctuation la
        # laissaient passer telle quelle jusqu'ici.
        text = _strip_greeting_preamble(raw_text).lower()
        confirmed = dict(state.get("confirmed", {}))
        # Snapshot pris AVANT que l'extraction ci-dessous ne mute confirmed/state
        # : sert de base a une eventuelle suspension (_suspend_for_topic_switch),
        # pour ne pas y reporter une capture erronee faite sur un message qui,
        # avec le recul, ne repondait pas au champ attendu.
        state_before_turn = copy.deepcopy(state)

        # Cloture spontanee (cas 29/30/37, voir _looks_like_resolution) :
        # verifiee seulement si un diagnostic est reellement en cours
        # (waiting_for truthy) -- un message "c'est bon" hors de tout contexte
        # de diagnostic actif n'a rien a cloturer ici, il suit son routage
        # normal (deny generique ou autre).
        if waiting_for and _looks_like_resolution(text):
            dispatcher.utter_message(
                text=pick(
                    "Tant mieux, ravi que ce soit réglé ! Autre chose pour laquelle je peux vous aider ?",
                    "Super, content que ça fonctionne à nouveau ! Puis-je faire autre chose pour vous ?",
                    "Parfait, c'est le principal ! N'hésitez pas si vous avez besoin d'autre chose.",
                ),
                buttons=QUICK_ACTION_BUTTONS,
            )
            return [
                {"event": "slot", "name": "diagnostic_state", "value": "{}"},
                {"event": "slot", "name": "pending_field", "value": None},
            ]

        # Colere/frustration (audit "robustesse comportementale", cas 21) :
        # accuse de reception bref PUIS on continue normalement (meme
        # principe que le hors-sujet, cas 8) -- volontairement pas de
        # nouvel intent, voir le commentaire sur la regle "Ignore
        # nlu_fallback/deny/affirm..." dans rules.yml pour pourquoi
        # inappropriate_language est reutilise tel quel ici plutot qu'un
        # intent "frustration" separe.
        if waiting_for and (tracker.latest_message.get("intent") or {}).get("name") == "inappropriate_language":
            dispatcher.utter_message(
                text="Je comprends votre frustration, je fais le maximum pour avancer rapidement avec vous."
            )

        # --- 1) Classification dynamique (ex action_classify_service) ---
        # Fraiche seulement si aucun champ n'etait deja en attente : sur les
        # tours suivants (reponse a un champ, confirmation oui/non...), le
        # texte courant ne decrit plus le probleme -- sa classification est
        # sans rapport avec la question posee et ne doit rien afficher a
        # l'utilisateur (montrer "aucune capacite reconnue" juste avant une
        # reponse par ailleurs parfaitement valide donnait une fausse
        # impression d'echec, constate en pratique).
        is_fresh_classification = not waiting_for

        # Cas 11 : memorise l'avertissement conditionnel sans rien changer
        # au routage de ce tour -- seulement lu plus tard par
        # _respond_engine_outcome si le diagnostic finit par escalader.
        if _looks_like_conditional_escalation_warning(text):
            state["_escalation_warned"] = True

        # Regle 5 (4e cas) : signal frais a CE tour (pas accumule) -- lu par
        # _mark_no_capability_matched pour sauter directement a la
        # proposition de ticket quand l'utilisateur vient de dire que le
        # probleme persiste, plutot que de reposer une question de narrowing.
        # `_user_reported_persistence` (accumule, jamais remis a False) sert
        # uniquement a nuancer le libelle final (voir
        # _respond_no_capability_matched) si le signal etait present a un
        # tour precedent mais plus sur celui-ci.
        persistence_signal = _looks_like_persistent_complaint(text)
        if persistence_signal:
            state["_user_reported_persistence"] = True
        state["_persistence_signal_this_turn"] = persistence_signal

        problems = _fetch_capabilities()
        # None = panne reseau vers FastAPI, a distinguer de "aucun mot-cle ne
        # correspond" : sans ca, une panne du service ressemblait pour
        # l'utilisateur a "votre probleme n'est pas reconnu", masquant une
        # panne technique derriere un message qui semble le blamer lui.
        service_unavailable = problems is None
        # Segmentation seulement sur une classification fraiche (pas de
        # waiting_for) : pendant l'extraction d'une reponse a un champ deja
        # pose, on veut le score du message ENTIER tel quel (voir
        # _looks_like_new_topic juste plus bas, qui compare a ce candidats
        # pour detecter une bascule de sujet) -- segmenter interfererait avec
        # ce mecanisme deja valide, sans benefice ici.
        if is_fresh_classification:
            candidates, multi_problem_detected = _score_capabilities_multi(text, problems or [])
        else:
            # apply_family_tiebreak=False : ce chemin alimente
            # _looks_like_new_topic, qui utilise volontairement une marge
            # plus stricte (TOPIC_SWITCH_RELATIVE_MARGIN=0.20) pour rester
            # rare en cours de diagnostic. Un ecart inter-services de 2%
            # suffirait a satisfaire artificiellement cette barre a 20% si
            # le tiebreak inter-services s'appliquait ici -- on le reserve
            # donc a la classification initiale (_score_capabilities_multi
            # et le narrowing post-echec, qui gardent le defaut).
            candidates, multi_problem_detected = (
                _score_capabilities(text, problems or [], apply_family_tiebreak=False)[:MAX_CANDIDATES],
                False,
            )
        # Pas de liste brute de candidats affichee a l'utilisateur (les noms
        # de capacites internes ne sont pas un langage utilisateur) : la
        # question ou le recapitulatif qui suit (plus bas) nomme deja le
        # probleme retenu une fois la decision prise -- l'annoncer ici en
        # plus, avant meme cette decision, etait redondant et confus des que
        # plusieurs candidats coexistaient.
        #
        # Audit ton/clarite : l'annonce "je vais transmettre votre demande
        # DIRECTEMENT" qui etait ici a ete retiree -- service_unavailable=True
        # mene, dans ce meme tour, a _respond_no_capability_matched (plus
        # bas dans le fichier) qui demande explicitement la PERMISSION de
        # creer un ticket ("Voulez-vous que je crée un ticket de réclamation
        # directement ?"). Les deux messages se contredisaient (fait accompli
        # puis demande de permission pour la meme chose) -- seul le second,
        # qui reflete le VRAI comportement (une confirmation est requise),
        # est conserve.

        # --- 2) Extraction (ex action_extract_diagnostic_entities) ---
        if waiting_for:
            ctx = _DiagnosticContext(dispatcher, tracker, state, confirmed, text)
            handler = EXTRACTION_HANDLERS.get(waiting_for, _extract_field_answer)
            handler(ctx)

            # Cas symetrique, pour l'etat "plusieurs choix proposes" : contrairement
            # au champ verrouille ci-dessous, aucun template_id n'est jamais fixe
            # tant qu'un choix n'a pas ete valide (voir _mark_pending_choices) --
            # le garde-fou par template_id ne peut donc jamais se declencher ici,
            # et un message qui ne correspond a aucun des choix offerts (numero ou
            # nom, voir _extract_priority_choice) rechargeait indefiniment la MEME
            # liste figee, meme si ce message decrit sans ambiguite un tout autre
            # probleme (constate en pratique : "j'ai recharge mon compte..." apres
            # une liste de choix sur un tout autre sujet). Rien n'a encore ete
            # collecte a ce stade (contrairement au cas template_id verrouille) :
            # pas besoin de demander confirmation avant d'abandonner la liste, on
            # reclasse directement des que le nouveau message a lui-meme un
            # gagnant net.
            if (
                waiting_for == "priority_choice"
                and "chosen_candidate" not in state
                and _has_meaningful_margin(candidates, CLASSIFICATION_RELATIVE_MARGIN)
            ):
                state.pop("pending_choices", None)

            # Changement de sujet probable : seulement si (a) un probleme
            # etait deja verrouille (template_id) -- avant verrouillage, il
            # n'y a rien de concret a proteger d'une reprise -- et (b)
            # l'extraction qui vient de tourner n'apporte pas de preuve
            # fiable que ce message repond bien au champ attendu (voir
            # _extraction_confidently_succeeded : une reponse peut a la fois
            # sembler valide ET decrire un tout autre probleme).
            if state_before_turn.get("template_id") and not _extraction_confidently_succeeded(state, waiting_for):
                new_topic_candidate = _looks_like_new_topic(state_before_turn, candidates)
                if new_topic_candidate is not None:
                    return _suspend_for_topic_switch(state_before_turn, dispatcher, tracker)

        state["confirmed"] = confirmed
        state["message"] = raw_text
        # Lu par _capture_opportunistic_nlu_entities au moment du verrouillage
        # (ci-dessous et dans _lock_new_template) : le nom de champ EXACT vu
        # par le NLU (entity.get("entity")) ne survit pas au-dela de ce tour
        # via `text`/`raw_text` seuls, il faut les entites elles-memes.
        state["message_entities"] = tracker.latest_message.get("entities", [])

        # --- 3) Mise a jour de l'etat (ex action_update_diagnostic_state) ---
        state["status"] = "in_progress"

        chosen = state.pop("chosen_candidate", None)
        if chosen:
            state["service_id"] = chosen["service_id"]
            state["template_id"] = chosen["problem_id"]
            state["template_name"] = chosen["label"]
            state["required_fields"] = chosen["required_fields"]
            state["optional_fields"] = chosen["optional_fields"]
            state["fallback_fields"] = chosen.get("fallback_fields", [])
            state["field_specs"] = chosen["field_specs"]
            state.pop("pending_choices", None)
            # Meme reset que dans _lock_new_template ci-dessus, pour le meme
            # bug potentiel via ce chemin de verrouillage parallele (choix
            # explicite apres plusieurs candidats a egalite).
            state["no_capability_matched"] = False
            state["narrowing_attempted"] = False
            # Meme capture opportuniste que _lock_new_template : ce chemin
            # verrouille aussi un probleme (apres narrowing de service), sur
            # le meme message dont les entites peuvent deja repondre a un
            # champ requis.
            _capture_opportunistic_field_patterns(state, confirmed, state.get("message") or "")
            _capture_opportunistic_nlu_entities(state, confirmed, state.get("message_entities") or [])

        # Recalcule a chaque tour (pas seulement mis a True) : sans ce reset
        # explicite, une detection multi-probleme d'un tour precedent
        # resterait figee a True indefiniment et court-circuiterait
        # _has_single_clear_winner sur tous les tours suivants, y compris
        # apres que l'utilisateur ait deja choisi sa priorite.
        state["_multi_problem_detected"] = multi_problem_detected
        _run_classification_rules(state, candidates, service_unavailable, problems or [])

        # Trace uniquement le VERROUILLAGE d'un nouveau probleme (comparaison
        # a state_before_turn, capture avant ce tour), pas chaque tour d'une
        # conversation deja verrouillee -- sinon chaque reponse a un champ
        # requis (waiting_for) reproduirait le meme evenement en boucle pour
        # rien. Couvre les deux chemins de verrouillage possibles : les
        # regles de classification (_lock_new_template, CLASSIFICATION_RULES
        # ci-dessus) ET le choix explicite d'un candidat ambigu (`chosen`,
        # juste au-dessus) -- les deux ecrivent template_id de la meme facon,
        # une seule comparaison suffit pour capturer les deux.
        new_template_id = state.get("template_id")
        if new_template_id and new_template_id != state_before_turn.get("template_id"):
            _report_agent_action(
                session_id=tracker.sender_id,
                domain="diagnostic_classification",
                action_type="problem_classified",
                input_data={"text": raw_text},
                output_data={
                    "service_id": state.get("service_id"),
                    "problem_id": new_template_id,
                    "label": state.get("template_name"),
                    "top_candidates": [
                        {
                            "service_id": c.get("service_id"),
                            "problem_id": c.get("problem_id"),
                            "confidence": c.get("confidence"),
                        }
                        for c in (candidates or [])[:MAX_CANDIDATES]
                    ],
                },
            )

        pending_field = state.get("waiting_for") or None
        # Pas de message generique ici : la question specifique au champ
        # (_respond_field_question, RESPONSE_HANDLERS...) ou le resultat
        # final, juste en dessous, portent deja toute l'information utile a
        # l'utilisateur -- un message intermediaire comme "je dois encore
        # recueillir : transaction_reference" exposait un nom de champ
        # interne au lieu d'une vraie question, sans rien ajouter.

        state_events = [
            {"event": "slot", "name": "pending_field", "value": pending_field},
            {"event": "slot", "name": "diagnostic_state", "value": json.dumps(state, ensure_ascii=False)},
        ]
        reset_events = [
            {"event": "slot", "name": "diagnostic_state", "value": "{}"},
            {"event": "slot", "name": "pending_field", "value": None},
        ]

        # --- 4) Question suivante ou resolution (ex action_next_diagnostic_question) ---
        if pending_field in RESPONSE_HANDLERS:
            result = RESPONSE_HANDLERS[pending_field](state, dispatcher, tracker, state_events, reset_events)
        elif pending_field:
            result = _respond_field_question(state, dispatcher, tracker, state_events, pending_field)
        elif state.get("no_capability_matched"):
            result = _respond_no_capability_matched(state, dispatcher, tracker, reset_events)
        else:
            result = _respond_engine_outcome(state, dispatcher, tracker, state_events, reset_events)

        # Question FAQ residuelle (audit "robustesse comportementale", cas
        # 9/11) : uniquement sur une classification fraiche (meme garde que
        # la segmentation multi-problemes) -- pendant l'extraction d'un
        # champ, "raw_text" est une reponse a la question posee, pas un
        # nouveau message potentiellement mixte. Ajoutee APRES la reponse
        # principale (pas a la place), en complement silencieux si le
        # service FAQ ne trouve rien (voir _search_faq).
        if is_fresh_classification:
            trailing_question = _extract_trailing_faq_question(raw_text)
            if trailing_question:
                faq_answer = _search_faq(trailing_question)
                if faq_answer:
                    dispatcher.utter_message(text=f"Au fait, à propos de « {trailing_question} » : {faq_answer}")

        return result


class ActionDecideEscalation(Action):

    def name(self) -> Text:
        return "action_decide_escalation"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        text = (tracker.latest_message.get("text") or "").lower()
        if "ticket" in text or "réclamation" in text or "support" in text:
            dispatcher.utter_message(text="Je vais préparer une réclamation préremplie avec les informations déjà collectées.")
            return [
                {"event": "slot", "name": "claim_requested", "value": True},
                {"event": "slot", "name": "ticket_source", "value": "user_diagnostic_escalation"},
            ]

        dispatcher.utter_message(text="Je vais poursuivre le diagnostic du problème avant toute escalade.")
        return [{"event": "slot", "name": "claim_requested", "value": False}]


class ActionHandleNegation(Action):

    def name(self) -> Text:
        return "action_handle_negation"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(text="Aucune réclamation ne sera créée. Je poursuis le diagnostic du problème.")
        return [
            {"event": "slot", "name": "claim_requested", "value": False},
            {"event": "slot", "name": "escalation_reason", "value": "negation"},
        ]


class ActionDefaultFallback(Action):
    """Remplace le fallback natif de Rasa (voir core_fallback_action_name
    dans config.yml) pour couvrir un cas precis : une reponse mal classee
    (deny/affirm/nlu_fallback, ex. une reference de transaction) qui resout
    ou escalade le diagnostic DANS LE MEME appel a action_run_diagnostic_step.

    Ce dernier remet alors pending_field a null, ce qui casse la condition de
    la regle "Ignore nlu_fallback/deny/affirm misclassification while
    diagnostic dialogue is pending" (rules.yml) pour son propre pas final
    (action_listen) -- constate en pratique via inspection du tracker.
    RulePolicy perd sa confiance sur ce pas precis et le fallback natif prend
    la main, affichant "je n'ai pas compris" alors que la demande a deja ete
    traitee et qu'une proposition de ticket vient d'etre affichee.

    Plutot que de declarer ce changement d'etat dans la regle (echoue a
    l'entrainement : Rasa exige alors que TOUTES les regles utilisant
    action_run_diagnostic_step, y compris "Route diagnostic requests" sans
    rapport avec ce cas, declarent le meme slot -- erreur "Incomplete
    rules"), on detecte ici la situation precise et on n'affiche pas le
    message trompeur.
    """

    def name(self) -> Text:
        return "action_default_fallback"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        last_action = next(
            (
                event.get("name")
                for event in reversed(tracker.events)
                if event.get("event") == "action" and event.get("name") != "action_default_fallback"
            ),
            None,
        )
        if last_action == "action_run_diagnostic_step":
            # Ne pas se contenter de `return []` : sans evenement, l'etat du
            # tracker ne change pas du tout, donc Core re-predit
            # action_default_fallback a l'identique -- constate en pratique
            # (boucle sur place jusqu'a la limite interne de predictions par
            # tour, sans jamais atteindre action_listen). FollowupAction force
            # explicitement le prochain pas, sans dependre d'une prediction de
            # policy sur cet etat ambigu.
            return [{"event": "followup", "name": "action_listen"}]

        # "+ 1" : au moment ou cette action s'execute, le tracker recu ne
        # contient PAS ENCORE l'evenement de CETTE execution (Core ne
        # l'ajoute qu'apres avoir reçu la reponse de l'action) --
        # _consecutive_fallback_count ne compte donc que les fallbacks
        # PRECEDENTS. Sans ce "+ 1", constate en pratique (grande vague de
        # tests conversationnels) : 3 fallbacks consecutifs reels
        # (action_default_fallback x3) ne declenchaient PAS encore
        # l'escalade -- il fallait un 4e fallback pour que la comparaison
        # passe enfin a Vrai, un utilisateur en subissait donc un de plus que
        # prevu par FALLBACK_ESCALATION_THRESHOLD avant d'etre oriente vers
        # le support humain.
        if _consecutive_fallback_count(tracker) + 1 >= FALLBACK_ESCALATION_THRESHOLD:
            # Trop d'incomprehensions de suite : plutot que de repeter le
            # meme message generique, on oriente vers le support humain (voir
            # _human_support_message, rasa/actions/common.py).
            dispatcher.utter_message(text=_human_support_message())
        else:
            # Boutons de relance ici (pas dans la branche support humain
            # au-dessus) : cette branche n'est atteinte que quand ni un
            # formulaire de reclamation ni une question de diagnostic ne sont
            # en attente (voir le early-return juste au-dessus pour ce
            # dernier cas) -- l'incomprehension est donc "sèche", le moment
            # ideal pour rappeler concretement ce que le bot sait faire.
            dispatcher.utter_message(response="utter_default", buttons=QUICK_ACTION_BUTTONS)
        # "rewind", pas "user_utterance_reverted" : c'est le nom d'evenement
        # reellement serialise par rasa_sdk pour UserUtteranceReverted (voir
        # rasa_sdk.events) -- le litteral "user_utterance_reverted" est rejete
        # par la validation JSON Schema de la reponse de l'action, ce qui
        # invalide TOUTE la reponse (pas seulement cet evenement) : le message
        # utter_default ci-dessus etait donc lui aussi perdu, laissant
        # l'utilisateur sans aucune reponse (constate en pratique : "Aucune
        # reponse recue du bot" pendant reclamation_form, mais le bug touche
        # n'importe quel fallback hors flux diagnostic, pas seulement celui-ci).
        return [{"event": "rewind"}]


class ActionOutOfScope(Action):
    """Remplace utter_out_of_scope declenchee directement comme action --
    meme principe que ActionDefaultFallback ci-dessus, pour la meme famille
    de probleme constatee en pratique : une reponse mal classee (ex. une
    reference de transaction classee "out_of_scope" au lieu de
    "affirm"/"deny"/"nlu_fallback", deja geres par la regle "Ignore
    nlu_fallback/deny/affirm misclassification while diagnostic dialogue is
    pending" dans rules.yml) alors qu'une question de diagnostic est en
    attente. Rasa n'a pas de negation dans ses regles ("n'importe quelle
    intention SAUF X/Y") : plutot que de rallonger indefiniment la liste
    blanche de cette regle a chaque nouvelle intention decouverte par
    hasard, ce garde-fou intercepte ici, au niveau de l'action elle-meme --
    la meme reponse a ce type de bug qui a deja fonctionne pour
    action_default_fallback.
    """

    def name(self) -> Text:
        return "action_out_of_scope"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        if tracker.get_slot("pending_field"):
            # Une question de diagnostic est en attente : ce message est
            # plus probablement une tentative de reponse mal classee qu'un
            # vrai hors-sujet. FollowupAction force le prochain pas, comme
            # pour action_default_fallback (sans lui, rien ne garantit que
            # Core route reellement vers le diagnostic ensuite).
            return [{"event": "followup", "name": "action_run_diagnostic_step"}]

        # Audit robustesse (test large 500+) : meme raison, mais pour
        # reclamation_form -- une approche par REGLES distinctes selon
        # active_loop ("Out of scope response" vs "Ignore out_of_scope
        # misclassification while reclamation form is active") s'est averee
        # peu fiable en pratique : apres le rejet interne du formulaire sur
        # un intent liste dans reclamation_form.ignored_intents (domain.yml),
        # RulePolicy ne matche pas toujours de facon deterministe l'etat
        # post-rejet (action_execution_rejected + loop_interrupted), et
        # TEDPolicy peut predire une action differente de celle voulue.
        # Gerer ce cas ICI, dans l'action elle-meme (comme deja fait pour
        # pending_field ci-dessus), evite totalement cette ambiguite de
        # regles : deterministe, independant de RulePolicy/TEDPolicy.
        if tracker.active_loop_name == "reclamation_form":
            return [{"event": "followup", "name": "reclamation_form"}]

        # "+ 1" : voir le commentaire equivalent dans ActionDefaultFallback
        # ci-dessus -- meme decalage d'un cran, meme correctif.
        if _consecutive_fallback_count(tracker) + 1 >= FALLBACK_ESCALATION_THRESHOLD:
            dispatcher.utter_message(text=_human_support_message())
        else:
            # Memes raisons que ActionDefaultFallback ci-dessus : atteint
            # seulement hors formulaire/diagnostic en attente (les deux cas
            # sont deja sortis via followup plus haut).
            dispatcher.utter_message(response="utter_out_of_scope", buttons=QUICK_ACTION_BUTTONS)
        return []


class ActionRespectfulLanguage(Action):
    """Remplace utter_please_be_respectful declenchee directement comme
    action -- meme principe que ActionOutOfScope juste au-dessus (voir sa
    docstring pour le detail de l'ambiguite RulePolicy/TEDPolicy observee en
    pratique sur les intents listes dans reclamation_form.ignored_intents).

    Ne dispatche PAS son propre message quand un diagnostic est en attente :
    action_run_diagnostic_step a deja son propre accuse de reception adapte
    au contexte ("Je comprends votre frustration, je fais le maximum...",
    voir son commentaire "Colere/frustration... cas 21") et continue de
    traiter le texte comme une reponse au champ en attente -- dispatcher
    utter_please_be_respectful ICI EN PLUS produirait deux messages
    empiles pour un seul tour.
    """

    def name(self) -> Text:
        return "action_respectful_language_reminder"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        if tracker.get_slot("pending_field"):
            return [{"event": "followup", "name": "action_run_diagnostic_step"}]

        dispatcher.utter_message(response="utter_please_be_respectful")
        if tracker.active_loop_name == "reclamation_form":
            return [{"event": "followup", "name": "reclamation_form"}]
        return []
