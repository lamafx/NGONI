"""Lecture a chaud des seuils du moteur (LIVE_PARAMETERS, voir service.py) par
les consommateurs internes a FastAPI -- aujourd'hui le repli manuel des
moteurs bge_sklearn (app/domains/nlu/engines.py). Rasa, lui, passe par
GET /settings/engine (router.py) : il tourne dans un autre processus.

Cache tres court plutot qu'une requete SQL par message : un classifieur est
appele a chaque tour, un seuil change quelques fois par jour. Une ecriture
depuis l'admin vide le cache (invalidate(), appele par PATCH
/admin/settings/parameters/{id}) -- la modification s'applique donc au
message suivant cote FastAPI, sous REFRESH_SECONDS cote Rasa.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from sqlalchemy.exc import SQLAlchemyError

from .service import SystemParameterService

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 5.0

# (lu_a, {param_id: valeur}) -- process unique/mono-worker deja suppose
# ailleurs (voir app/main.py, avertissement WEB_CONCURRENCY) : un simple
# module-level suffit, meme choix que _prediction_cache dans engines.py.
_cache: Optional[Tuple[float, Dict[str, float]]] = None


def live_overrides() -> Dict[str, float]:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < REFRESH_SECONDS:
        return _cache[1]

    # Import paresseux, meme raison que FaqService.enqueue_faq_batch :
    # importer ce module (via engines.py) ne doit pas exiger une base joignable.
    try:
        from app.database import SessionLocal
    except ImportError:  # pragma: no cover - support running as `main`
        from database import SessionLocal

    try:
        session = SessionLocal()
        try:
            values = SystemParameterService.from_session(session).live_overrides()
        finally:
            session.close()
    except SQLAlchemyError as exc:
        # Base injoignable : on garde la derniere valeur connue plutot que de
        # retomber en silence sur les defauts -- un seuil resserre depuis
        # l'admin ne doit pas se relacher tout seul pendant une coupure.
        logger.warning("[Settings] Lecture des seuils impossible, derniere valeur conservee : %s", exc)
        values = _cache[1] if _cache is not None else {}

    _cache = (now, values)
    return values


def live_value(param_id: str, default: float) -> float:
    return live_overrides().get(param_id, default)


def invalidate() -> None:
    global _cache
    _cache = None
