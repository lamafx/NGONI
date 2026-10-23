"""Authentification interne des futures routes admin du moteur FastAPI --
meme patron que ngoni-core-service (voir
ngoni-core-service/src/common/internalAuth.js::assertInternalAuth/getAdminId) :
un secret partage en en-tete X-Internal-Secret (pas d'authentification
utilisateur individuelle -- coherent avec le reste du perimetre assistant,
voir docs/13-limitations.md §13.1), et X-User-ID pour savoir QUI a agi
(tracabilite, jamais une preuve d'identite en soi).

Aucune route n'utilise encore cette dependance au moment ou ce module est
introduit -- volontairement en place AVANT la premiere route admin plutot
qu'ajoutee apres coup, pour qu'aucune route admin ne soit jamais ecrite sans
elle des le depart (voir docs/14-evolutions.md §14.1)."""

import logging
import os

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

# Valeurs manifestement non-securisees : les memes que celles deja utilisees
# comme defauts de developpement ailleurs dans ce projet (voir
# wallet_service/security.py, WALLET_SERVICE_INTERNAL_SECRET="test-secret") --
# jamais acceptables pour un secret qui protege une route d'administration,
# meme en developpement.
_INSECURE_PLACEHOLDER_VALUES = {"", "changeme", "test-secret"}

ADMIN_INTERNAL_SECRET = os.getenv("ADMIN_INTERNAL_SECRET", "")


def admin_secret_is_configured() -> bool:
    return ADMIN_INTERNAL_SECRET not in _INSECURE_PLACEHOLDER_VALUES


def warn_if_admin_secret_missing() -> None:
    """Appele une seule fois au demarrage (app/main.py::startup). N'arrete
    jamais le process : aucune route n'utilise encore cette dependance au
    moment ou ce module est introduit (voir docstring), un arret dur pour un
    secret pas encore charge de sens serait premature -- voir le meme
    raisonnement que les autres politiques de resilience de ce projet
    (app.domains.diagnostic.pipeline). Le jour ou une premiere route admin
    est ajoutee, ce message devient le signal a ne pas manquer avant tout
    deploiement au-dela du poste de developpement."""
    if not admin_secret_is_configured():
        logger.warning(
            "[FastAPI] ADMIN_INTERNAL_SECRET n'est pas configure (ou vaut une "
            "valeur de developpement par defaut) -- toute route admin utilisant "
            "require_admin_auth refusera systematiquement les requetes tant "
            "qu'un vrai secret n'est pas defini dans l'environnement."
        )


def require_admin_auth(
    x_internal_secret: str = Header(..., alias="X-Internal-Secret"),
) -> None:
    """Dependance FastAPI a appliquer sur chaque route admin (voir
    contracts/diagnostic/README.md §5 pour la meme convention deja utilisee
    entre le Diagnostic Engine et les microservices : Depends(require_admin_auth)
    sur le router entier, comme fastify.addHook('preHandler', assertInternalAuth)
    cote ngoni-core-service). Ferme par defaut : si ADMIN_INTERNAL_SECRET
    n'est pas configure (ou vaut un placeholder connu, voir
    _INSECURE_PLACEHOLDER_VALUES), AUCUNE requete n'est jamais acceptee --
    pas de repli permissif possible."""
    if not admin_secret_is_configured() or x_internal_secret != ADMIN_INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")


def get_admin_id(x_user_id: str | None = Header(None, alias="X-User-ID")) -> str | None:
    """Identite de l'admin appelant, pour tracabilite uniquement (voir
    audit.agent_actions / diagnostic_audit_log pour la meme convention
    d'en-tete) -- jamais une preuve d'authentification en soi : seul
    require_admin_auth protege la route, cette fonction ne fait que
    documenter qui a agi une fois l'acces deja autorise."""
    return x_user_id or None
