import logging
import re
import uuid as uuid_module
from typing import Dict, List, NamedTuple, Optional, Sequence

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


class FaqAnswer(NamedTuple):
    question: str
    answer: str
    score: float


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

        query_embedding = embed_query(question)
        match = self.repository.find_closest(query_embedding, locale=detected_locale)
        if match is None and detected_locale != DEFAULT_LOCALE:
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
            match = self.repository.find_closest(query_embedding, locale=DEFAULT_LOCALE)

        if match is None:
            logger.info("[FAQ] Aucun FAQ trouvé en base pour locale=%s.", detected_locale)
            return None

        item, score = match
        logger.info("[FAQ] Meilleur score=%.3f pour question=%r (matched=%r)", score, question, item.question)

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
