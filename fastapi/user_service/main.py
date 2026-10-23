"""Service local de user-service, pour tester le Diagnostic Engine quand le
vrai ngoni-user-service (Laravel 11 + Docker + Postgres) n'est pas
accessible en local.

NE REMPLACE JAMAIS les tests du vrai ngoni-user-service, qui restent la
seule source de verite sur son comportement. Ce service sert uniquement a
valider que le Diagnostic Engine (registry/adapter/pipeline) sait vraiment
parler HTTP a ce service, avec le meme contrat.

N'IMPACTE JAMAIS le vrai ngoni-user-service : c'est un processus totalement
separe, qui ne touche a aucun fichier ni route de ngoni-user-service. Pour
l'utiliser, on redirige simplement le Diagnostic Engine vers lui via la
variable d'environnement USER_SERVICE_BASE_URL -- rien d'autre ne change
dans le workflow des requetes.

Organisation du package (voir README.md pour le detail) :
    security.py       -- verification du secret partage (X-Internal-Secret)
    outcomes.py        -- construction des reponses RESOLVED/ESCALATE
    db.py              -- modeles SQLAlchemy en lecture seule sur le schema `users`
    diagnostic/
        manifest.py    -- Capability Manifest (5 problemes)
        router.py      -- endpoints FastAPI, sans aucune logique metier
        formatting.py  -- formatage de dates commun aux services/
        services/      -- un fichier par probleme (logique de resolution) :
                          kyc.py, account_status.py, compliance.py,
                          deletion.py, parental_consent.py

Les donnees sont lues en LECTURE SEULE dans le schema Postgres `users` de
chatbotdb -- un CLONE de la vraie base de ngoni-user-service. Aucun endpoint
de seed n'existe ici : les cas de test se choisissent directement parmi les
lignes reelles clonees (voir README.md).

Lancement :
    fastapi/.venv/Scripts/python.exe -m uvicorn user_service.main:app \
        --app-dir C:\\DEV\\PFE\\fastapi --port 3104
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

# Meme raison que wallet_service/main.py : process uvicorn separe, root logger a
# configurer explicitement pour que les logger.info(...) applicatifs (voir
# user_service/diagnostic/router.py) s'affichent dans ce terminal.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from .diagnostic.router import router as diagnostic_router
from .support import router as support_router

app = FastAPI(title="user-service — service de diagnostic (usage local uniquement)")
app.include_router(diagnostic_router)
app.include_router(support_router)
