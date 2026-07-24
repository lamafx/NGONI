from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.audit.service import record_faq_lookup
from .repository import FaqRepository
from .schemas import (
    FaqCategoryGroup,
    FaqCreate,
    FaqDebugCandidate,
    FaqDebugSearchResponse,
    FaqItemResponse,
    FaqSearchFlow,
    FaqSearchRequest,
    FaqSearchResponse,
    FaqSuggestionItem,
    FaqSuggestionMatch,
    FaqSuggestionsResponse,
)
from .service import DEFAULT_THRESHOLD, SECONDARY_THRESHOLD, FaqService

router = APIRouter(prefix="/faq", tags=["faq"])


@router.post("/", status_code=202)
def create_faq(request: List[FaqCreate], background_tasks: BackgroundTasks):
    if not request:
        raise HTTPException(status_code=400, detail="Aucune FAQ fournie.")

    background_tasks.add_task(FaqService.enqueue_faq_batch, request)
    return {"queued": len(request)}


@router.get("/", response_model=List[FaqItemResponse])
def list_faqs(db: Session = Depends(get_db)):
    repository = FaqRepository(db)
    service = FaqService(repository)
    return service.list_faqs()


@router.get("/by-slug/{slug}", response_model=FaqItemResponse)
def get_faq_by_slug(slug: str, db: Session = Depends(get_db)):
    """Utilisee par le clic sur une suggestion "vouliez-vous dire..."
    (audit FAQ #8, voir ActionSelectFaqQuestion, rasa/actions/faq.py) quand
    la question n'est pas deja dans le cache faq_suggestions_cache (chemin
    normal via /faq/suggestions) -- ces suggestions viennent de /faq/search
    (statut "not_found") qui ne renvoie que question+slug+score, jamais la
    reponse complete tant qu'elle n'est pas explicitement choisie.
    Route enregistree apres /faq/random, /faq/suggestions, /faq/debug (pas
    de conflit : FastAPI tente les routes fixes avant celle-ci, dans l'ordre
    de declaration)."""
    repository = FaqRepository(db)
    service = FaqService(repository)
    item = service.get_by_slug(slug)
    if item is None:
        raise HTTPException(status_code=404, detail="FAQ introuvable.")
    return item


@router.get("/random", response_model=List[str])
def random_faq_questions(count: int = Query(2, ge=1, le=10), db: Session = Depends(get_db)):
    """Utilisee par le message d'accueil (rasa/actions/greeting.py) pour
    suggerer des exemples concrets de questions plutot qu'un message
    generique. `count` borne (1-10) : evite qu'un appel mal forme ne demande
    un tri aleatoire sur un nombre demesure de lignes."""
    repository = FaqRepository(db)
    service = FaqService(repository)
    return service.get_random_questions(count=count)


@router.get("/suggestions", response_model=FaqSuggestionsResponse)
def random_faq_suggestions(count: int = Query(10, ge=1, le=10), db: Session = Depends(get_db)):
    """Utilisee par le bouton "Voir des questions frequentes" (voir
    ActionBrowseFaq, rasa/actions/faq.py) : contrairement a /faq/random
    (liste plate de questions, sans reponse), renvoie des questions
    aleatoires regroupees par categorie pour un affichage depliable cote
    client (web ou mobile, meme contrat JSON pour les deux). Inclut la
    reponse de chaque question (contrairement a /faq/random) : le client
    (ou le cache de conversation Rasa, voir faq_suggestions_cache) doit
    pouvoir afficher la reponse au clic sans requete supplementaire vers
    la base."""
    repository = FaqRepository(db)
    service = FaqService(repository)
    grouped = service.get_random_suggestions(count=count)
    return FaqSuggestionsResponse(
        categories=[
            FaqCategoryGroup(
                category=category,
                questions=[
                    FaqSuggestionItem(
                        slug=item.slug, question=item.question, answer=item.answer, category=item.category
                    )
                    for item in items
                ],
            )
            for category, items in grouped.items()
        ]
    )


@router.post("/search", response_model=FaqSearchResponse)
def search_faq(payload: FaqSearchRequest, db: Session = Depends(get_db)):
    """Route attendue par Rasa (action_faq_search, voir rasa/actions/faq.py)
    quand l'intention ask_faq est reconnue directement par Rasa -- ex. une
    conversation qui parle au webhook Rasa sans passer par /api/chat
    (celui-ci court-circuite deja vers FaqService directement pour le
    frontend en production). Cette route manquait jusqu'ici : Rasa appelait
    une adresse qui n'existait pas, echouant silencieusement (capture par
    `except requests.RequestException` cote action) a chaque fois que ce
    chemin etait emprunte. Reutilise le meme FaqService que /api/chat --
    aucune logique dupliquee, seule la porte d'entree differe.
    """
    repository = FaqRepository(db)
    service = FaqService(repository)
    result = service.find_best_answer(payload.question)

    record_faq_lookup(
        db,
        question=payload.question,
        matched_question=result.question if result else None,
        score=result.score if result else None,
    )

    if result is None:
        # None couvre desormais deux cas distincts (voir find_best_answer) :
        # base vide, OU un candidat existe mais sous le seuil de confiance --
        # la note precedente ("Aucune FAQ trouvée en base") mentait dans ce
        # second cas, laissant croire a une base vide alors qu'un candidat
        # avait ete ecarte a raison.
        #
        # Audit FAQ #8 (16.6) : plutot que de s'arreter sur cet echec, on
        # retente avec le second seuil (SECONDARY_THRESHOLD < DEFAULT_THRESHOLD)
        # pour proposer jusqu'a 3 candidats en clarification ("vouliez-vous
        # dire...") -- suggestions reste [] si rien ne franchit meme ce
        # second seuil, le statut reste "not_found" dans tous les cas (les
        # suggestions sont un complement, pas une reponse confirmee).
        suggestions = service.find_top_matches(payload.question)
        return FaqSearchResponse(
            answer=None,
            flow=FaqSearchFlow(
                status="not_found",
                note="Aucune FAQ suffisamment pertinente trouvée.",
            ),
            suggestions=[
                FaqSuggestionMatch(question=match.question, slug=match.slug, score=match.score)
                for match in suggestions
            ],
        )

    # find_best_answer ne renvoie plus jamais un score sous le seuil (voir
    # son commentaire) : "matched" est donc le seul statut possible ici
    # desormais. matched_question (audit FAQ #4) : ce champ existait dans le
    # schema mais n'etait jamais peuple, affichant "aucune" cote Rasa meme
    # sur un match a 0.987 -- find_best_answer renvoie maintenant la question
    # FAQ effectivement matchee, pas seulement sa reponse.
    return FaqSearchResponse(
        answer=result.answer,
        flow=FaqSearchFlow(
            status="matched",
            note=f"Score de similarité : {result.score:.3f}",
            matched_question=result.question,
        ),
    )


@router.post("/debug/search", response_model=FaqDebugSearchResponse)
def search_faq_debug(
    payload: FaqSearchRequest, k: int = Query(5, ge=1, le=20), db: Session = Depends(get_db)
):
    """Outillage de recalibration (16.6, P1) : renvoie les `k` meilleurs
    candidats et leurs deux scores (semantique brut, hybride avec boost
    mots-cles) SANS filtrage par seuil -- y compris sous DEFAULT_THRESHOLD.
    N'est jamais appelee par le flux Rasa (voir rasa/actions/faq.py,
    FAQ_SERVICE_URL pointe sur /faq/search, pas ici) : reservee a un futur
    script de recalibration qui rejouerait un corpus de test contre cette
    route pour tracer precision/rappel a plusieurs seuils, sans avoir a
    reconfigurer DEFAULT_THRESHOLD a chaque essai.
    """
    repository = FaqRepository(db)
    service = FaqService(repository)
    candidates = service.get_debug_candidates(payload.question, k=k)
    return FaqDebugSearchResponse(
        candidates=[
            FaqDebugCandidate(
                question=item.question, slug=item.slug, semantic_score=semantic_score, hybrid_score=hybrid_score
            )
            for item, hybrid_score, semantic_score in candidates
        ],
        default_threshold=DEFAULT_THRESHOLD,
        secondary_threshold=SECONDARY_THRESHOLD,
    )
