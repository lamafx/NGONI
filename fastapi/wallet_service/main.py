"""Service local de wallet-service, pour tester le Diagnostic Engine quand le
vrai wallet-service (PHP 8.3 + Docker + Postgres) n'est pas accessible en
local (ex: environnement de test en staging uniquement).

NE REMPLACE JAMAIS les tests Pest de ngoni-wallet-service
(tests/Feature/DiagnosticControllerTest.php), qui restent la seule source de
verite sur le comportement du vrai wallet-service. Ce service sert uniquement a
valider que le Diagnostic Engine (registry/adapter/pipeline) sait vraiment
parler HTTP a un service externe, avec le meme contrat.

N'IMPACTE JAMAIS le vrai wallet-service : c'est un processus totalement
separe, qui ne touche a aucun fichier ni route de ngoni-wallet-service. Pour
l'utiliser, on redirige simplement le Diagnostic Engine vers lui via la
variable d'environnement WALLET_SERVICE_BASE_URL -- rien d'autre ne change
dans le workflow des requetes.

Organisation du package (voir README.md pour le detail) :
    security.py       -- verification du secret partage (X-Internal-Secret)
    outcomes.py       -- construction des reponses RESOLVED/ESCALATE
    db.py             -- modeles SQLAlchemy en lecture seule sur le schema `wallet`
    diagnostic/
        manifest.py   -- Capability Manifest (3 problemes)
        router.py     -- endpoints FastAPI, sans aucune logique metier
        formatting.py -- formatage de dates/durees commun aux services/
        services/     -- un fichier par probleme (logique de resolution,
                         porte manuelle de DiagnosticController.php) :
                         withdrawal.py, topup.py, gift.py

Les donnees sont lues en LECTURE SEULE dans le schema Postgres `wallet` de
chatbotdb -- un CLONE de la vraie base de ngoni-wallet-service (voir
app/database.py pour la connexion). Aucun endpoint de seed n'existe ici : il
n'y a plus lieu d'inserer de fausses donnees par-dessus un clone de
production, les cas de test se choisissent directement parmi les lignes
reelles clonees (voir README.md).

Lancement :
    fastapi/.venv/Scripts/python.exe -m uvicorn wallet_service.main:app \
        --app-dir C:\\DEV\\PFE\\fastapi --port 3103
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

# Meme raison que app/main.py : process uvicorn separe, root logger a
# configurer explicitement pour que les logger.info(...) applicatifs (voir
# wallet_service/diagnostic/router.py) s'affichent dans ce terminal.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from .diagnostic.router import router as diagnostic_router

app = FastAPI(title="wallet-service — service de diagnostic (usage local uniquement)")
app.include_router(diagnostic_router)
