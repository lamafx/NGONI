import logging
import re
import uuid as uuid_module
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from langdetect import LangDetectException, detect

from app.shared.embeddings import embed_passage, embed_query

from .models import FaqCategory, FaqItem
from .repository import FaqRepository
from .schemas import FaqCreate

logger = logging.getLogger(__name__)

# Locale de secours quand la langue de l'utilisateur n'est pas detectable, ou
# quand aucun contenu FAQ n'existe encore dans la langue detectee (voir
# find_best_answer). C'est la seule langue dans laquelle le contenu FAQ est
# redige aujourd'hui.
DEFAULT_LOCALE = "fr"

# Audit FAQ #6 : langdetect est statistiquement peu fiable sous ce nombre de
# caracteres (frequemment observe sur un mot ou deux) -- sous ce seuil, on
# utilise directement DEFAULT_LOCALE plutot que de risquer une locale
# erronee qui ferait chercher dans la mauvaise langue.
MIN_LENGTH_FOR_LANGDETECT = 15

# Audit FAQ #7 : aucun plafond n'existait auparavant, meme surface
# d'epuisement de ressources que les champs libres cote Rasa (voir
# reclamation.py). Tronque plutot que de rejeter : au-dela de ce nombre de
# caracteres, le surplus n'ajoute de toute facon rien d'utile a une question.
MAX_QUESTION_LENGTH = 500

# RECALIBRE (2026-07) suite au passage e5-small -> e5-base (voir
# app/shared/embeddings/service.py) : l'ancien seuil de 0.87 avait ete
# calibre pour e5-small et n'est pas transposable tel quel a e5-base, dont la
# distribution de scores est differente. Mesure en leave-one-out sur les 15
# vraies questions FAQ en base + 10 negatifs (salutations, small-talk, et
# quelques vraies plaintes diagnostic qui ne doivent PAS declencher de
# reponse FAQ) :
#   0.83 : FP=4/10 (40%)  TP=12/15 (80%)
#   0.84 : FP=2/10 (20%)  TP=10/15 (67%)  <- des salutations passent encore
#   0.85 : FP=0/10 (0%)   TP=9/15 (60%)   <- retenu : 1er seuil sans faux positif
#   0.86 : FP=0/10 (0%)   TP=7/15 (47%)
#   0.87 : FP=0/10 (0%)   TP=6/15 (40%)   <- ancien seuil : moins bon rappel
#          que 0.85, pour le meme 0% de faux positifs sur ce corpus
# 0.85 domine strictement l'ancien 0.87 sur ce test (meme absence de faux
# positif, meilleur rappel) -- pas un compromis, contrairement au choix fait
# a l'epoque pour 0.87 sur e5-small. Echantillon volontairement petit (15
# questions reelles) : a recalibrer si le catalogue FAQ grossit
# significativement ou si l'usage reel montre trop de faux positifs/negatifs.
DEFAULT_THRESHOLD = 0.85

# Audit FAQ #7 (16.5/16.6) : la colonne `keywords` (ARRAY(Text), deja en
# base sur les 26 lignes reelles du catalogue) etait ecrite a la creation
# mais jamais relue en recherche -- seul l'embedding semantique tranchait.
# Boost borne, PAS un recalcul complet du score : un chevauchement exact de
# mots-cles ajoute au plus MAX_KEYWORD_BOOST au score cosinus, jamais de quoi
# a lui seul faire gagner un candidat nettement moins proche semantiquement.
# Objectif cible (16.5 #7) : rattraper une partie des cas "not_found" du
# registre familier/SMS ou l'orthographe degradee fait decrocher l'embedding
# sous le seuil alors qu'un mot-cle exact reste present.
#
# ATTENTION calibration : DEFAULT_THRESHOLD (0.85) a ete calibre sur le score
# cosinus SEUL (voir commentaire ci-dessus, leave-one-out 15+10). Ce boost
# deplace legerement la frontiere reelle -- pas re-calibre ici (necessite le
# corpus de 306 paires de l'audit du 16 juillet, non committe, voir
# docs/16-audit-faq-nlu-2026-07.md 16.6). A revisiter lors d'une vraie
# recalibration de DEFAULT_THRESHOLD.
KEYWORD_BOOST_PER_MATCH = 0.02
MAX_KEYWORD_BOOST = 0.05

# Audit FAQ #8 (16.6) : nombre de candidats remontes de la base pour le
# reclassement hybride ET pour les suggestions "vouliez-vous dire..." --
# doit rester superieur a 1 pour que le boost mots-cles puisse reellement
# changer l'ordre (un candidat legerement moins proche par cosinus peut
# repasser devant grace a ses mots-cles).
TOP_K_CANDIDATES = 5

# Second seuil, plus bas que DEFAULT_THRESHOLD (16.6, proposition Top-3) :
# candidats a proposer en clarification ("vouliez-vous dire : ... ?") quand
# aucun ne franchit DEFAULT_THRESHOLD, plutot qu'un "je n'ai pas trouve" sec.
SECONDARY_THRESHOLD = 0.75

# Audit FAQ #9 (16.6, dedup catalogue) : score cosinus au-dela duquel deux
# questions sont considerees quasi-identiques (garde-fou a l'ecriture,
# FaqService.add_faq) -- volontairement tres au-dessus de DEFAULT_THRESHOLD
# (retrieval) : deux formulations differentes d'un meme sujet doivent pouvoir
# matcher la meme FAQ (0.85) sans etre pour autant traitees comme le MEME
# doublon a l'ecriture (0.97). Pas de mesure de calibration dediee (comme
# 16.6 le note pour le dedup) : valeur de depart delibere, a ajuster si des
# faux positifs/negatifs sont observes en usage reel.
DUPLICATE_THRESHOLD = 0.97


class FaqAnswer(NamedTuple):
    question: str
    answer: str
    score: float


class FaqMatch(NamedTuple):
    # Candidat de clarification ("vouliez-vous dire...") -- contrairement a
    # FaqAnswer, expose le slug (necessaire pour reutiliser le meme mecanisme
    # de bouton que ActionSelectFaqQuestion, rasa/actions/faq.py) plutot que
    # la reponse complete (pas encore choisie par l'utilisateur a ce stade).
    question: str
    slug: str
    score: float


def _keyword_overlap_boost(normalized_question: str, keywords: Sequence[str]) -> float:
    if not keywords:
        return 0.0
    matches = sum(
        1
        for keyword in keywords
        if keyword and re.search(rf"\b{re.escape(keyword.lower())}\b", normalized_question)
    )
    return min(matches * KEYWORD_BOOST_PER_MATCH, MAX_KEYWORD_BOOST)


def detect_locale(text: str) -> str:
    # langdetect renvoie des codes ISO 639-1 (ex: "fr", "en", "es"), le meme
    # format que la colonne locale de core.faq_items -- pas de conversion
    # necessaire. Sur un texte trop court/ambigu pour etre fiable, on ne
    # tente meme pas (voir MIN_LENGTH_FOR_LANGDETECT) ; sur un texte plus
    # long mais neanmoins ambigu, langdetect leve LangDetectException : on
    # retombe alors sur la locale par defaut plutot que de propager l'erreur.
    if len(text.strip()) < MIN_LENGTH_FOR_LANGDETECT:
        return DEFAULT_LOCALE
    try:
        return detect(text)
    except LangDetectException:
        return DEFAULT_LOCALE


def _slugify(question: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-") or "faq"
    return f"{slug[:140]}-{uuid_module.uuid4().hex[:8]}"


class FaqService:
    def __init__(self, repository: FaqRepository) -> None:
        self.repository = repository

    def add_faq(self, data: FaqCreate) -> FaqItem:
        # embed_passage (pas embed_query) : une FAQ stockee est le document
        # compare, pas la requete -- meme convention que les capacites de
        # diagnostic (voir app/domains/diagnostic/registry.py). Modele
        # partage (app.shared.embeddings) : voir son docstring, un seul
        # modele charge par process, reutilise par tous les domaines.
        embedding = embed_passage(data.question)

        # Garde-fou anti-doublon (audit FAQ #9, 16.2/16.6) : 5 doublons exacts
        # decouverts a l'audit du 16 juillet (catalogue.faq_items) --
        # comparaison passage/passage (meme convention d'embedding que les
        # lignes deja en base), pas query/passage comme find_best_answer.
        # N'empeche pas l'ecriture (pas d'exception : POST /faq/ reste un
        # traitement best-effort en arriere-plan, voir enqueue_faq_batch),
        # se contente de ne PAS inserer un quasi-doublon et de renvoyer
        # l'existant a la place -- un futur appelant qui inspecterait le
        # retour verrait le slug existant, pas un nouveau.
        duplicate = self.repository.find_closest(embedding, locale=data.locale)
        if duplicate is not None:
            existing_item, score = duplicate
            if score >= DUPLICATE_THRESHOLD:
                logger.warning(
                    "[FAQ] Doublon probable ignoré (score=%.3f) : %r proche de %r déjà en base (slug=%s).",
                    score, data.question, existing_item.question, existing_item.slug,
                )
                return existing_item

        item = FaqItem(
            question=data.question,
            answer=data.answer,
            category=data.category,
            keywords=data.keywords,
            is_featured=data.is_featured,
            sort_order=data.sort_order,
            locale=data.locale,
            slug=data.slug or _slugify(data.question),
            status=data.status,
            show_on_mobile=data.show_on_mobile,
            show_on_web=data.show_on_web,
            embedding=embedding,
        )
        return self.repository.add(item)

    def list_faqs(self) -> List[FaqItem]:
        return self.repository.list_all()

    def get_by_slug(self, slug: str) -> Optional[FaqItem]:
        return self.repository.find_by_slug(slug)

    def get_random_questions(self, count: int = 2, locale: str = DEFAULT_LOCALE) -> List[str]:
        # Utilise par le message d'accueil (rasa/actions/greeting.py) pour
        # suggerer des exemples de questions concrets plutot qu'un message
        # generique -- seul le texte de la question est renvoye, jamais la
        # reponse (pas besoin de la divulguer avant que l'utilisateur ne la
        # pose vraiment).
        items = self.repository.find_random(count, locale=locale)
        return [item.question for item in items]

    def get_random_suggestions(
        self, count: int = 10, locale: str = DEFAULT_LOCALE
    ) -> Dict[FaqCategory, List[FaqItem]]:
        # Utilise pour le bouton "Voir des questions frequentes" (voir
        # ActionBrowseFaq, rasa/actions/faq.py) : mêmes questions aleatoires
        # que get_random_questions, mais regroupees par categorie pour un
        # affichage depliable cote client. Ordre des groupes = ordre de
        # declaration de FaqCategory (stable d'un appel a l'autre), pas
        # l'ordre aleatoire des items eux-memes.
        items = self.repository.find_random(count, locale=locale)
        by_category: Dict[FaqCategory, List[FaqItem]] = {}
        for item in items:
            by_category.setdefault(item.category, []).append(item)
        return {category: by_category[category] for category in FaqCategory if category in by_category}

    def _ranked_candidates(
        self, query_embedding: List[float], normalized_question: str, locale: str, k: int = TOP_K_CANDIDATES
    ) -> List[Tuple[FaqItem, float, float]]:
        # Renvoie (item, score_hybride, score_semantique_brut) tries par
        # score hybride decroissant -- score_semantique_brut conserve
        # separement pour le logging/debug (voir find_best_answer,
        # router.py::search_faq_debug), le score hybride seul pilote la
        # decision. k > 1 necessaire : le boost mots-cles peut faire
        # remonter un candidat que le cosinus seul aurait classe 2e ou 3e.
        raw_candidates = self.repository.find_top_k(query_embedding, k=k, locale=locale)
        scored = [
            (item, min(semantic_score + _keyword_overlap_boost(normalized_question, item.keywords), 1.0), semantic_score)
            for item, semantic_score in raw_candidates
        ]
        scored.sort(key=lambda entry: entry[1], reverse=True)
        return scored

    def find_best_answer(
        self, question: str, locale: Optional[str] = None, threshold: float = DEFAULT_THRESHOLD
    ) -> Optional[FaqAnswer]:
        # locale=None (par defaut) : detecte automatiquement la langue du
        # message plutot que de forcer "fr" -- l'ancien comportement
        # renvoyait toujours du contenu francais meme a un utilisateur ayant
        # ecrit dans une autre langue. Un appelant peut toujours forcer une
        # locale explicite (ex. un test) en la passant directement.
        question = question.strip()[:MAX_QUESTION_LENGTH]
        detected_locale = locale or detect_locale(question)
        normalized_question = question.lower()

        query_embedding = embed_query(question)
        candidates = self._ranked_candidates(query_embedding, normalized_question, detected_locale)
        if not candidates and detected_locale != DEFAULT_LOCALE:
            # Aucun contenu FAQ publie dans la langue detectee : on retombe
            # sur la locale par defaut (seule langue couverte aujourd'hui)
            # plutot que de ne renvoyer aucune reponse du tout. La reponse
            # reste en francais dans ce cas -- pas de traduction automatique
            # pour l'instant (choix explicite) : ce log sert a mesurer la
            # frequence reelle de ce decalage avant d'investir dans une
            # traduction.
            logger.info(
                "[FAQ] Aucun contenu publié pour locale=%s, repli sur locale=%s (réponse non traduite).",
                detected_locale, DEFAULT_LOCALE,
            )
            candidates = self._ranked_candidates(query_embedding, normalized_question, DEFAULT_LOCALE)

        if not candidates:
            logger.info("[FAQ] Aucun FAQ trouvé en base pour locale=%s.", detected_locale)
            return None

        item, score, semantic_score = candidates[0]
        logger.info(
            "[FAQ] Meilleur score=%.3f (sémantique=%.3f) pour question=%r (matched=%r)",
            score, semantic_score, question, item.question,
        )

        if score < threshold:
            # Audit FAQ #1 (deja corrige) : les deux branches renvoyaient
            # auparavant la meme chose, rendant `threshold` totalement
            # inoperant. None signale desormais reellement "rien d'assez
            # pertinent" aux deux appelants (main.py:/api/chat, qui retombe
            # deja correctement sur le webhook Rasa standard ; router.py:
            # /faq/search, qui renvoie deja answer=None + status="not_found").
            logger.info("[FAQ] Score trop faible (%.3f < %.3f), aucune réponse renvoyée.", score, threshold)
            return None

        return FaqAnswer(question=item.question, answer=str(item.answer), score=score)

    def find_top_matches(
        self, question: str, locale: Optional[str] = None, k: int = 3, threshold: float = SECONDARY_THRESHOLD
    ) -> List[FaqMatch]:
        """Audit FAQ #8 (16.6) : jusqu'a `k` candidats dont le score hybride
        franchit `threshold` (< DEFAULT_THRESHOLD) -- destine a une
        clarification "vouliez-vous dire : ... ?" quand find_best_answer ne
        renvoie rien (aucun candidat n'a franchi DEFAULT_THRESHOLD), plutot
        que de laisser l'utilisateur sur un echec silencieux. Appele
        separement de find_best_answer (pas de court-circuit automatique) :
        router.py decide explicitement quand proposer des suggestions.
        """
        question = question.strip()[:MAX_QUESTION_LENGTH]
        detected_locale = locale or detect_locale(question)
        normalized_question = question.lower()

        query_embedding = embed_query(question)
        candidates = self._ranked_candidates(query_embedding, normalized_question, detected_locale, k=max(k, TOP_K_CANDIDATES))
        if not candidates and detected_locale != DEFAULT_LOCALE:
            candidates = self._ranked_candidates(query_embedding, normalized_question, DEFAULT_LOCALE, k=max(k, TOP_K_CANDIDATES))

        return [
            FaqMatch(question=item.question, slug=item.slug, score=score)
            for item, score, _ in candidates[:k]
            if score >= threshold
        ]

    def get_debug_candidates(
        self, question: str, locale: Optional[str] = None, k: int = TOP_K_CANDIDATES
    ) -> List[Tuple[FaqItem, float, float]]:
        """Prerequis d'outillage pour une future recalibration de
        DEFAULT_THRESHOLD (16.6) : expose les candidats et leurs scores tels
        quels, sans filtrage par seuil -- reservee a un endpoint de debug
        (router.py::search_faq_debug), jamais appelee par le flux Rasa normal.
        """
        question = question.strip()[:MAX_QUESTION_LENGTH]
        detected_locale = locale or detect_locale(question)
        normalized_question = question.lower()
        query_embedding = embed_query(question)
        return self._ranked_candidates(query_embedding, normalized_question, detected_locale, k=k)

    @staticmethod
    def enqueue_faq_batch(records: Sequence[FaqCreate]) -> None:
        from app.database import SessionLocal

        total = len(records)
        if total == 0:
            logger.info("[FAQ] Aucun élément à traiter.")
            return

        session = SessionLocal()
        try:
            repository = FaqRepository(session)
            service = FaqService(repository)
            for index, data in enumerate(records, start=1):
                service.add_faq(data)
                percent = int(index * 100 / total)
                logger.info("[FAQ] Stockage des FAQ : %d%% (%d/%d)", percent, index, total)
            logger.info("[FAQ] Traitement terminé : %d FAQ enregistrées.", total)
        finally:
            session.close()
