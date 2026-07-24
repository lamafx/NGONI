"""Endpoint d'embedding partage : un seul modele charge dans ce process
(voir service.py), appele par tout consommateur qui a besoin d'une
similarite semantique (Rasa pour le matching de probleme diagnostic,
potentiellement d'autres a l'avenir) sans avoir a charger le modele
lui-meme."""

from fastapi import APIRouter

from .schemas import EmbedBatchRequest, EmbedBatchResponse, EmbedRequest, EmbedResponse
from .service import embed_query, embed_query_batch

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


@router.post("/query", response_model=EmbedResponse)
def embed_query_endpoint(payload: EmbedRequest) -> EmbedResponse:
    return EmbedResponse(embedding=embed_query(payload.text))


@router.post("/query/batch", response_model=EmbedBatchResponse)
def embed_query_batch_endpoint(payload: EmbedBatchRequest) -> EmbedBatchResponse:
    return EmbedBatchResponse(embeddings=embed_query_batch(payload.texts))
