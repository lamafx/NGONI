from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.audit.service import record_faq_lookup
from .repository import FaqRepository
from .schemas import (
    FaqCategoryGroup,
    FaqCreate,
    FaqItemResponse,
    FaqSearchFlow,
    FaqSearchRequest,
    FaqSearchResponse,
    FaqSuggestionItem,
    FaqSuggestionsResponse,
)
from .service import FaqService

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
        return FaqSearchResponse(
            answer=None,
            flow=FaqSearchFlow(
                status="not_found",
                note="Aucune FAQ suffisamment pertinente trouvée.",
            ),
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
