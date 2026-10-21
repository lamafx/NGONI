"""Routes cote CLIENT de la prise en charge humaine (l'espace conseiller,
lui, vit dans admin_router.py, derriere require_admin_auth).

Deux besoins seulement, volontairement :
  - demander explicitement un conseiller (« Escalader vers un agent
    humain ») sans passer par une phrase que le NLU devrait classer -- c'est
    le bouton de l'interface, pas un message ;
  - recuperer ce qui a ete dit depuis le dernier affichage, puisqu'une
    reponse de conseiller n'arrive PAS en retour de POST /api/chat (elle est
    ecrite plus tard, depuis un autre poste).

Interrogation periodique (polling) et non WebSocket : le moteur n'a
aujourd'hui aucune infrastructure temps reel (ni broker, ni gestion de
connexions persistantes), et en introduire une pour ce seul usage
demanderait de la deployer/superviser. Un GET conditionnel toutes les
quelques secondes suffit a l'echelle visee.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

try:
    from app.database import get_db
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db

from .schemas import (
    ConversationMemoryResponse,
    ConversationUpdatesResponse,
    EscalateRequest,
    TurnRequest,
    TurnResponse,
    WithdrawRequest,
    WithdrawResponse,
)
from .service import ConversationNotFoundError, ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/escalate", response_model=ConversationUpdatesResponse)
def escalate_conversation(payload: EscalateRequest, db: Session = Depends(get_db)):
    """Place la conversation dans la file des conseillers. Ne coupe pas le
    bot : tant que personne n'a pris la main, l'assistant continue de
    repondre (voir ConversationService.is_muted)."""
    service = ConversationService.from_session(db)
    service.escalate(
        payload.conversation_id,
        reason=payload.reason or "demande_utilisateur",
        user_id=payload.user_id,
    )
    return ConversationUpdatesResponse(**service.updates_for_user(payload.conversation_id))


@router.post("/withdraw", response_model=WithdrawResponse)
def withdraw_escalation(payload: WithdrawRequest, db: Session = Depends(get_db)):
    """Annule une demande de conseiller encore en attente : la conversation
    sort de la file et l'assistant reste aux commandes. Si un conseiller l'a
    deja prise, rien n'est annule (`withdrawn: false`) -- il est deja en
    train de traiter le dossier."""
    service = ConversationService.from_session(db)
    try:
        withdrawn, conversation = service.withdraw(payload.conversation_id, reason=payload.reason)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation introuvable") from exc
    return WithdrawResponse(
        conversation_id=conversation.conversation_id,
        status=conversation.status,
        withdrawn=withdrawn,
        assigned_to=conversation.assigned_to,
    )


@router.post("/turns", response_model=TurnResponse, status_code=201)
def record_turn(payload: TurnRequest, db: Session = Depends(get_db)):
    """Journalise un tour complet (message de l'usager + reponses du bot) pour
    les clients qui interrogent Rasa directement -- voir TurnRequest pour le
    pourquoi. Renvoie l'etat de prise en charge : c'est ce que le client lit
    pour savoir s'il doit cesser d'interroger Rasa et attendre un humain."""
    service = ConversationService.from_session(db)
    conversation = service.record_user_message(
        payload.conversation_id,
        payload.user_text,
        user_id=payload.user_id,
        intent=payload.intent,
        confidence=payload.confidence,
    )
    if payload.bot_messages:
        service.record_bot_messages(
            payload.conversation_id,
            [{"text": message.text, **message.metadata} for message in payload.bot_messages],
        )
    return TurnResponse(
        conversation_id=conversation.conversation_id,
        status=conversation.status,
        handoff=service.is_muted(payload.conversation_id),
        assigned_to=conversation.assigned_to,
    )


@router.get("/memory", response_model=ConversationMemoryResponse)
def conversation_memory(
    user_id: str = Query(..., min_length=1, max_length=200),
    exclude: Optional[str] = Query(
        None, description="Conversation en cours, a ne pas se rappeler a elle-meme."
    ),
    db: Session = Depends(get_db),
):
    """Memoire entre conversations : le dernier sujet reel de cet utilisateur
    et le statut actuel du ticket qui en est ne. Lue par l'accueil de
    l'assistant (rasa/actions/greeting.py) pour reprendre le fil."""
    return ConversationMemoryResponse(
        **ConversationService.from_session(db).memory_for_user(user_id, exclude)
    )


@router.get("/{conversation_id}/updates", response_model=ConversationUpdatesResponse)
def conversation_updates(
    conversation_id: str,
    after: Optional[datetime] = Query(
        None,
        description="Ne renvoyer que les messages postérieurs à cet instant (ISO 8601) — "
        "typiquement le `checked_at` de l'appel précédent.",
    ),
    db: Session = Depends(get_db),
):
    try:
        return ConversationUpdatesResponse(
            **ConversationService.from_session(db).updates_for_user(conversation_id, after=after)
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation introuvable") from exc
