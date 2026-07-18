← [Sommaire](README.md) | [9. Configuration](09-configuration.md)

# 10. Déploiement

> Ce chapitre décrit le déploiement en **environnement de développement
> local** (Windows), seul environnement actuellement supporté par ce projet
> — voir [13. Limitations actuelles](13-limitations.md).

## 10.1 Pré-requis

- Python 3.11+ avec `venv` (utilisé pour `fastapi/.venv`)
- Docker Desktop (pour `rasa` et `actions`)
- PostgreSQL 15 accessible localement (natif ou via l'image `postgres:15-alpine`)
- PowerShell (environnement de référence de ce projet)

## 10.2 Ce qui tourne en conteneur vs nativement sur l'hôte

`docker-compose.yml` définit cinq services (`rasa`, `actions`, `postgres`,
`pgadmin`, `fastapi`), mais **seuls `rasa` et `actions` sont utilisés en
conteneur dans le fonctionnement réel de ce projet** :

| Composant | Où il tourne en pratique | Pourquoi |
|---|---|---|
| `rasa` | Conteneur Docker (`pfe-rasa-1`) | Isolation de l'environnement Rasa (dépendances lourdes, versions figées) |
| `actions` | Conteneur Docker (`pfe-actions-1`) | Idem, processus séparé du runtime Rasa (voir [4.2](04-services.md#42-service-actions)) |
| Moteur FastAPI | **Processus natif** (`fastapi/.venv`) | Cycle d'itération plus rapide (rechargement à chaud `--reload`, débogueur local), pas de rebuild d'image à chaque changement |
| `wallet_stub` / `user_stub` | **Processus natifs** (même venv que le moteur) | Idem |
| PostgreSQL | **Instance native** sur l'hôte | Partagée par le moteur natif et le tracker Rasa (atteint depuis les conteneurs via `host.docker.internal`) |
| pgAdmin | Généralement non utilisé au quotidien | Outil d'inspection ponctuel |

Lancer `docker compose up`/`build` pour `fastapi` ou `postgres` créerait des
conteneurs concurrents sur les mêmes ports (`8000`, `5432`) que les
processus natifs déjà en place, avec un état/une configuration différents —
**à éviter** dans ce projet.

## 10.3 Installation

```powershell
# Environnement Python du moteur (et des stubs, même venv)
cd C:\DEV\PFE\fastapi
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env    # puis éditer les valeurs (voir 9. Configuration)

# Fichiers d'environnement Rasa
Copy-Item rasa\.env.example rasa\.env
Copy-Item rasa\actions\.env.example rasa\actions\.env
```

## 10.4 Ordre de démarrage recommandé

1. **PostgreSQL** (natif, doit déjà tourner — base `chatbotdb`, utilisateur
   `chatbot_user`, voir `readme.md` à la racine pour les identifiants de
   développement).
2. **Rasa + Actions** (Docker) :
   ```powershell
   docker compose up -d rasa actions
   ```
3. **Moteur FastAPI** (natif) — attend automatiquement que Rasa réponde
   (`wait_for_rasa()` dans `app/main.py`) avant de terminer son démarrage :
   ```powershell
   cd C:\DEV\PFE\fastapi
   .venv\Scripts\python.exe -m uvicorn app.main:app --reload --host localhost --port 8000
   ```
4. **Stubs wallet/user** (natifs, nécessaires pour que le Diagnostic Engine
   ait au moins un service à interroger) :
   ```powershell
   cd C:\DEV\PFE\fastapi
   .venv\Scripts\python.exe -m uvicorn wallet_stub.main:app --app-dir C:\DEV\PFE\fastapi --port 3103
   .venv\Scripts\python.exe -m uvicorn user_stub.main:app --app-dir C:\DEV\PFE\fastapi --port 3104
   ```

> Le moteur FastAPI précharge le modèle d'embeddings et le Capability
> Registry **avant** d'accepter du trafic (voir [7.5](07-integration-ia.md#chargement)) :
> le premier démarrage prend 10-20 secondes de plus que les suivants.

## 10.5 Commandes de lancement détaillées

Référence complète dans [`utils.txt`](../utils.txt) (racine du dépôt),
notamment pour surcharger la cible du Diagnostic Engine en une seule
session PowerShell sans passer par `.env` :

```powershell
cd C:\DEV\PFE\fastapi
$env:WALLET_SERVICE_BASE_URL = "http://127.0.0.1:3103/api/v1"
$env:WALLET_SERVICE_INTERNAL_SECRET = "test-secret"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

## 10.6 Vérifications post-déploiement

| Vérification | Commande | Attendu |
|---|---|---|
| Rasa a chargé un modèle | `curl http://localhost:5005/status` | `model_file` non vide |
| Moteur FastAPI opérationnel | `curl http://localhost:8000/diagnostic/capabilities` | Liste non vide si les stubs tournent |
| Stubs joignables | `curl http://localhost:3103/api/v1/diagnostic/manifest` (idem `3104`) | `CapabilityManifest` JSON valide |
| Bout-en-bout | Ouvrir `http://localhost:8000/chat` et envoyer un message | Réponse du bot affichée, intent/confiance visibles |

## 10.7 Réentraînement du modèle avant déploiement

```powershell
docker compose run --rm rasa train
docker compose exec rasa rasa test nlu --out results
```

Voir [7.8](07-integration-ia.md#78-déploiement-dun-nouveau-modèle-rasa-en-production)
pour la procédure complète (évaluation, rollback).

---

Suite : [11. Maintenance](11-maintenance.md)
