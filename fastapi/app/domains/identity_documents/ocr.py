"""Lecture OCR d'une image -- RapidOCR (modeles ONNX embarques dans le
paquet : aucun binaire systeme, aucun telechargement au premier appel,
fonctionne hors ligne).

Le moteur est charge une seule fois par process, a la premiere analyse, et
partage ensuite : le recreer a chaque requete coute plusieurs secondes."""

from __future__ import annotations

import io
import logging
import threading
from typing import List

import numpy as np
from PIL import Image

from .analyzer import OcrLine

logger = logging.getLogger(__name__)

# Au-dela, l'OCR ralentit sans lire mieux une piece d'identite.
MAX_SIDE_PX = 1600

_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr import RapidOCR  # import differe : ~1 s, seulement si utilise

            _engine = RapidOCR()
            logger.info("[ID-DOC] moteur OCR charge")
        return _engine


def read_lines(image: Image.Image) -> List[OcrLine]:
    """Lignes de texte lues, de haut en bas. Appel BLOQUANT (CPU) : a lancer
    hors de la boucle asyncio (voir router.py)."""
    image = image.convert("RGB")
    scale = MAX_SIDE_PX / max(image.size)
    if scale < 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)))
    result = _get_engine()(np.asarray(image)[:, :, ::-1])  # RGB -> BGR (OpenCV)
    if not result.txts:
        return []
    lines = []
    for text, score, box in zip(result.txts, result.scores, result.boxes):
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        lines.append(OcrLine(text=text, score=float(score), x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys)))
    lines.sort(key=lambda line: (line.y0, line.x0))
    return lines


def open_image(data: bytes) -> Image.Image:
    """Ouvre ET verifie l'image (Pillow.verify detecte un fichier tronque ou
    deguise) -- leve ValueError si ce n'est pas une image valide."""
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
        return image
    except Exception as error:  # Pillow leve des types tres varies
        raise ValueError(str(error)) from error
