"""Verification d'une piece d'identite envoyee dans le chat.

Chaine de controle, dans l'ordre -- chaque etape refuse avec une raison
lisible, affichee telle quelle a l'usager :
  1. le fichier : type declare, taille, contenu reellement decodable comme
     image JPEG/PNG/WebP (un PDF ou un fichier renomme est refuse ici) ;
  2. l'image : dimensions minimales pour qu'une piece soit lisible ;
  3. l'OCR puis le filtre : SEULES une carte nationale d'identite ou un
     passeport passent a l'extraction des champs (voir analyzer.py).

Quand l'appelant declare le compte (en-tete X-User-ID), la piece est
enregistree (ia.identity_documents) pour le conseiller humain qui devra la
valider : l'image seulement si la piece est ACCEPTEE, et une soumission KYC
« en attente » est ouverte cote user_service. Rien n'est journalise dans les
logs au-dela du type reconnu et de l'issue (aucune donnee d'identite)."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

try:
    from app.database import get_db
    from app.domains.support import client as support_client
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db
    from domains.support import client as support_client

from .analyzer import DOCUMENT_LABELS, analyze_lines
from .models import REVIEW_NOT_APPLICABLE, REVIEW_PENDING, IdentityDocument, document_summary
from .ocr import open_image, read_lines
from .schemas import DocumentAnalysisRequest, DocumentAnalysisResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/identity-documents", tags=["identity-documents"])

ACCEPTED_FORMATS = {"JPEG": "JPEG", "PNG": "PNG", "WEBP": "WebP"}
MAX_BYTES = 8 * 1024 * 1024
MIN_WIDTH, MIN_HEIGHT = 400, 250

GUIDANCE = "Merci d'envoyer une photo de votre carte nationale d'identité ou de votre passeport."


def _refuse(reason: str, check_label: str, check_value: str, started: float) -> DocumentAnalysisResponse:
    logger.info("[ID-DOC] refuse (%s)", check_label)
    return DocumentAnalysisResponse(
        accepted=False,
        document_type=None,
        reason=reason,
        message=f"Ce fichier n'est pas adapté. {reason} {GUIDANCE}",
        checks=[{"label": check_label, "value": check_value, "ok": False}],
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


@router.post("/analyze", response_model=DocumentAnalysisResponse)
async def analyze_document(
    payload: DocumentAnalysisRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID", max_length=200),
    db: Session = Depends(get_db),
):
    result, data = await _analyze(payload)
    if not x_user_id:
        return result

    document = IdentityDocument(
        user_id=x_user_id,
        conversation_id=payload.conversation_id,
        filename=payload.filename,
        content_type=payload.content_type,
        image=data if result.accepted else None,
        accepted=result.accepted,
        document_type=result.document_type,
        reason=result.reason,
        fields=[field.model_dump() for field in result.fields],
        checks=[check.model_dump() for check in result.checks],
        mrz_valid=result.mrz_valid,
        review_status=REVIEW_PENDING if result.accepted else REVIEW_NOT_APPLICABLE,
    )
    if result.accepted:
        # Nouvelle piece = nouvelle demande de verification, comme dans le
        # vrai parcours KYC : le diagnostic repond desormais « en cours
        # d'examen ». Sans effet si le compte est inconnu du user service.
        try:
            submission = support_client.open_kyc_submission(x_user_id)
            if submission:
                document.kyc_submission_id = uuid.UUID(submission["submission_id"])
                result.message = (
                    f"Document reconnu : {result.document_label.lower()}. J'ai extrait vos informations "
                    "d'identité et transmis la pièce pour vérification : un conseiller va la valider."
                )
        except support_client.ServiceUnavailable as exc:
            logger.warning("[ID-DOC] soumission KYC non ouverte : %s", exc)
    db.add(document)
    db.commit()
    result.document_id = str(document.id)
    return result


@router.get("/mine")
def my_documents(
    x_user_id: str = Header(..., alias="X-User-ID", min_length=1, max_length=200),
    db: Session = Depends(get_db),
):
    """Pieces envoyees par ce compte et leur examen (notifications du client)."""
    documents = (
        db.query(IdentityDocument)
        .filter(IdentityDocument.user_id == x_user_id, IdentityDocument.accepted.is_(True))
        .order_by(IdentityDocument.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        {key: value for key, value in document_summary(d).items() if key not in ("fields", "checks")}
        for d in documents
    ]


async def _analyze(payload: DocumentAnalysisRequest):
    """(reponse, octets de l'image) -- octets None si le fichier n'a pas pu
    etre decode."""
    started = time.perf_counter()
    content_type = (payload.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        kind = "un PDF" if "pdf" in content_type else f"un fichier « {content_type} »"
        return _refuse(
            f"Vous avez envoyé {kind} : seules les images (JPEG, PNG ou WebP) peuvent être analysées.",
            "Format du fichier",
            content_type,
            started,
        ), None

    data_b64 = payload.data_base64
    if data_b64.startswith("data:"):
        data_b64 = data_b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Contenu base64 invalide") from exc

    if len(data) > MAX_BYTES:
        return _refuse(
            f"Le fichier pèse {len(data) // (1024 * 1024)} Mo, la limite est de {MAX_BYTES // (1024 * 1024)} Mo.",
            "Taille du fichier",
            "trop volumineux",
            started,
        ), None

    try:
        image = open_image(data)
    except ValueError:
        return _refuse(
            "Son contenu n'est pas une image lisible (fichier endommagé ou d'un autre type).",
            "Format du fichier",
            "illisible",
            started,
        ), None
    if image.format not in ACCEPTED_FORMATS:
        return _refuse(
            f"Le format {image.format or 'inconnu'} n'est pas accepté : utilisez une image JPEG, PNG ou WebP.",
            "Format du fichier",
            image.format or "inconnu",
            started,
        ), data
    if image.width < MIN_WIDTH or image.height < MIN_HEIGHT:
        return _refuse(
            f"L'image est trop petite ({image.width} × {image.height} px) pour lire les mentions d'une pièce.",
            "Résolution",
            f"{image.width} × {image.height} px",
            started,
        ), data

    # L'OCR est un calcul CPU de quelques secondes : hors de la boucle asyncio,
    # pour ne pas geler le reste du moteur pendant l'analyse.
    lines = await asyncio.to_thread(read_lines, image)
    analysis = analyze_lines(lines)
    latency_ms = int((time.perf_counter() - started) * 1000)
    file_check = {
        "label": "Format du fichier",
        "value": f"image {ACCEPTED_FORMATS[image.format]} · {image.width} × {image.height} px",
        "ok": True,
    }
    logger.info(
        "[ID-DOC] %s type=%s champs=%d lignes=%d latence=%dms",
        "accepte" if analysis.accepted else "refuse",
        analysis.document_type,
        len(analysis.fields),
        len(lines),
        latency_ms,
    )

    if analysis.accepted:
        label = DOCUMENT_LABELS[analysis.document_type].lower()
        message = f"Document reconnu : {label}. J'en ai extrait vos informations d'identité."
    elif analysis.document_type is not None:
        message = analysis.reason
    else:
        message = f"Ce fichier n'est pas adapté. {analysis.reason} {GUIDANCE}"

    return DocumentAnalysisResponse(
        accepted=analysis.accepted,
        document_type=analysis.document_type,
        document_label=DOCUMENT_LABELS.get(analysis.document_type) if analysis.document_type else None,
        reason=analysis.reason,
        message=message,
        fields=analysis.fields if analysis.accepted else [],
        checks=[file_check, *analysis.checks],
        mrz_valid=analysis.mrz_valid,
        latency_ms=latency_ms,
    ), data
