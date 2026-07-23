"""Rate limiting basique sur les endpoints publics (docs/14-evolutions.md
14.1, docs/taches.txt P2 #16) -- portée volontairement réduite : aucun
endpoint de ce périmètre n'a d'authentification réelle (voir
docs/13-limitations.md, `app/shared/admin_auth.py` ne protège que
`/admin/complaints/*`), et corriger cela demande une décision produit sur le
mécanisme d'identité (JWT, session, fournisseur externe...), pas un choix
technique local -- hors de portée de cette session. Ce middleware ne
remplace donc PAS une authentification : il limite seulement le débit brut
par IP sur les endpoints les plus exposés, pour absorber un abus grossier
(script, boucle involontaire côté client) en attendant cette décision.

État en mémoire du process, pas distribué (Redis ou equivalent) --
cohérent avec l'avertissement déjà présent dans `app/main.py` (circuit
breakers/Capability Registry également en mémoire, single-process) : si
`WEB_CONCURRENCY > 1` un jour, chaque worker aura sa propre limite
indépendante (la limite réelle observée devient max_requests × nb_workers),
à revoir alors avec un backend partagé."""

import logging
import time
from collections import defaultdict, deque
from os import getenv
from typing import Deque, Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

RATE_LIMIT_MAX_REQUESTS = int(getenv("RATE_LIMIT_MAX_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = float(getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# Endpoints publics les plus exposés de ce périmètre : /api/chat (point
# d'entrée du frontend), /faq/search (appelé par Rasa à chaque intention
# ask_faq), /complaints/create et son alias /tickets/create (voir
# app/main.py, la route réellement appelée par rasa/actions/reclamation.py).
RATE_LIMITED_PATH_PREFIXES = ("/api/chat", "/faq/search", "/complaints/create", "/tickets/create")

# Purge periodique des cles totalement expirees (voir dispatch ci-dessous) :
# sans ca, une IP qui ne revient jamais laisse une entree vide mais
# persistante -- croissance non bornee sur un process de longue duree.
_CLEANUP_EVERY_N_REQUESTS = 1000


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """Fenetre glissante simple (deque d'horodatages) par (IP, chemin) --
    voir la docstring du module pour les limites assumees (mémoire
    process, pas de backend partagé)."""

    def __init__(
        self,
        app,
        max_requests: int = RATE_LIMIT_MAX_REQUESTS,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._requests_seen = 0

    def _cleanup_expired_keys(self, now: float) -> None:
        stale_keys = [
            key
            for key, hits in self._hits.items()
            if not hits or now - hits[-1] > self.window_seconds
        ]
        for key in stale_keys:
            del self._hits[key]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith(RATE_LIMITED_PATH_PREFIXES):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        key = (client_ip, path)
        now = time.monotonic()

        self._requests_seen += 1
        if self._requests_seen % _CLEANUP_EVERY_N_REQUESTS == 0:
            self._cleanup_expired_keys(now)

        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()

        if len(hits) >= self.max_requests:
            retry_after = max(1, int(self.window_seconds - (now - hits[0])))
            logger.warning(
                "[RateLimit] %s dépasse %d requêtes/%.0fs sur %s (429)",
                client_ip, self.max_requests, self.window_seconds, path,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Trop de requêtes, veuillez réessayer plus tard."},
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        return await call_next(request)
