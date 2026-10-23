"""Verification d'une piece d'identite envoyee dans le chat.

Chaine de controle, dans l'ordre -- chaque etape refuse avec une raison
lisible, affichee telle quelle a l'usager :
  1. le fichier : type declare, taille, contenu reellement decodable comme
     image JPEG/PNG/WebP (un PDF ou un fichier renomme est refuse ici) ;
  2. l'image : dimensions minimales pour qu'une piece soit lisible ;
  3. l'OCR puis le filtre : SEULES une carte nationale d'identite ou un
     passeport passent a l'extraction des champs (voir analyzer.py).

L'image n'est ni stockee ni journalisee : seuls le type reconnu et l'issue
le sont (aucune donnee d'identite dans les logs)."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time

from fastapi import APIRouter, HTTPException

from .analyzer import DOCUMENT_LABELS, analyze_lines
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
async def analyze_document(payload: DocumentAnalysisRequest):
    started = time.perf_counter()
    content_type = (payload.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        kind = "un PDF" if "pdf" in content_type else f"un fichier « {content_type} »"
        return _refuse(
            f"Vous avez envoyé {kind} : seules les images (JPEG, PNG ou WebP) peuvent être analysées.",
            "Format du fichier",
            content_type,
            started,
        )

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
        )

    try:
        image = open_image(data)
    except ValueError:
        return _refuse(
            "Son contenu n'est pas une image lisible (fichier endommagé ou d'un autre type).",
            "Format du fichier",
            "illisible",
            started,
        )
    if image.format not in ACCEPTED_FORMATS:
        return _refuse(
            f"Le format {image.format or 'inconnu'} n'est pas accepté : utilisez une image JPEG, PNG ou WebP.",
            "Format du fichier",
            image.format or "inconnu",
            started,
        )
    if image.width < MIN_WIDTH or image.height < MIN_HEIGHT:
        return _refuse(
            f"L'image est trop petite ({image.width} × {image.height} px) pour lire les mentions d'une pièce.",
            "Résolution",
            f"{image.width} × {image.height} px",
            started,
        )

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
    )
