# ngoni-ia-service

Microservice d'**assistance conversationnelle** pour la plateforme Ngoni : bot Rasa (NLU français) + moteur FastAPI (FAQ sémantique, diagnostic métier, réclamations, feedback).

## Rôle

Point d'entrée conversationnel de premier niveau capable de :

1. **Répondre aux FAQ** par similarité d'embeddings (résistant aux fautes / reformulations)
2. **Diagnostiquer un problème réel** en interrogeant `wallet-service` / `user-service` via un contrat HTTP versionné (Capability Registry)
3. **Escalader vers un humain** (ticket `CMP-…`) si le diagnostic conclut à une escalade ou si le service cible est injoignable
4. **Filtrer** hors-sujet / langage inapproprié (`vocabulary_guard`)
5. **Recueillir le feedback** (utile / pas utile, suggestions, plaintes)

Principe : *le microservice métier décide, le moteur transporte, Rasa affiche*.

Documentation détaillée : [`docs/`](docs/README.md) · Workflows : [`docs/WORKFLOW.md`](docs/WORKFLOW.md)

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Dialogue / NLU | Rasa (DIETClassifier, policies TED / Rule / Memoization) |
| Actions | Rasa Action Server (Python) |
| Moteur métier | FastAPI (domaines `faq`, `diagnostic`, `complaints`, `feedback`) |
| Embeddings | `sentence-transformers` / `intfloat/multilingual-e5-base` (dim 768) |
| Base de données | PostgreSQL 15 (+ extension `pgvector`) |
| Conteneurs (dev) | Docker Compose — `rasa` + `actions` uniquement |
| Ports | Rasa `5005` · Actions `5055` · FastAPI `8000` |

## Architecture (vue rapide)

```
Utilisateur → Rasa:5005 → Actions:5055 → FastAPI:8000
                                              ├── PostgreSQL (FAQ, tickets, audit, tracker Rasa)
                                              ├── wallet-service / stub :3103  (/diagnostic/*)
                                              └── user-service   / stub :3104  (/diagnostic/*)
```

Voir [docs/02-architecture.md](docs/02-architecture.md).

## Endpoints principaux

### Santé / test (moteur FastAPI `:8000`)

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/` | Accueil |
| GET | `/chat` | Widget de chat HTML (dev) |
| POST | `/api/parse` | Proxy NLU Rasa |
| POST | `/api/chat` | Chat de test (court-circuit FAQ si `ask_faq`) |

### FAQ

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/faq/` | Liste des FAQ |
| POST | `/faq/search` | Recherche sémantique |
| GET | `/faq/suggestions` | Suggestions groupées par catégorie |
| GET | `/faq/random` | Questions aléatoires |

### Diagnostic

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/diagnostic/capabilities` | Catalogue agrégé (consommé par Rasa) |
| POST | `/diagnostic/resolve` | Résolution / escalade (`X-User-ID` requis) |
| POST | `/diagnostic/escalate` | Relais ticket depuis un `EscalateOutcome` |

Outcomes : `RESOLVED` · `ESCALATE` · `NEED_MORE_INFO`

### Réclamations & feedback

| Méthode | Chemin | Description |
|---------|--------|-------------|
| POST | `/tickets/create` | Créer un ticket (`CMP-YYYYMMDD-…`) |
| GET | `/complaints/{ticket_id}` | Détail ticket |
| POST | `/feedback` | Suggestion / plainte |
| POST | `/feedback/ratings` | Notation utile / pas utile |

### Embeddings (partagés)

| Méthode | Chemin | Description |
|---------|--------|-------------|
| POST | `/embeddings/query` | Vecteur d'une requête |
| POST | `/embeddings/query/batch` | Lot de vecteurs |

### Rasa (`:5005`)

| Méthode | Chemin | Description |
|---------|--------|-------------|
| POST | `/webhooks/rest/webhook` | Canal conversationnel |
| POST | `/model/parse` | Classification NLU seule |
| GET | `/status` | Modèle chargé |

Référence complète : [docs/06-api-reference.md](docs/06-api-reference.md).

## Contrat diagnostic (microservices)

Tout service diagnosticable doit exposer :

| Route | Méthode |
|-------|---------|
| `/diagnostic/manifest` | GET |
| `/diagnostic/{problem_id}` | POST |

Schémas versionnés : `contracts/diagnostic/v1/` (quand le code applicatif sera présent dans le dépôt). En-têtes : `X-Internal-Secret`, `X-Request-ID`.

Services ciblés aujourd'hui : **wallet** (retraits, topup, cadeaux) et **user** (KYC, accès compte, compliance, suppression, consentement parental).

## Variables d'environnement (aperçu)

| Variable | Rôle |
|----------|------|
| `DATABASE_URL` | PostgreSQL (SQLAlchemy) |
| `WALLET_SERVICE_BASE_URL` | Stub ou wallet réel (`…/api/v1`) |
| `USER_SERVICE_BASE_URL` | Stub ou user réel |
| `WALLET_SERVICE_INTERNAL_SECRET` / `USER_SERVICE_INTERNAL_SECRET` | `X-Internal-Secret` |
| `REGISTRY_POLL_INTERVAL_SECONDS` | Rafraîchissement Capability Registry (défaut 300) |
| `RASA_PARSE_URL` / `RASA_WEBHOOK_URL` | Proxy interface de test |
| Actions : `FAQ_*`, `DIAGNOSTIC_*`, `EMBEDDING_*`, `TICKET_*`, `FEEDBACK_*` | URLs vers le moteur (`host.docker.internal:8000` en Docker Desktop) |

Détail : [docs/09-configuration.md](docs/09-configuration.md).

## Lancer en local

Prérequis : Python 3.11+, Docker Desktop, PostgreSQL 15 local.

```bash
# 1. Postgres natif (base chatbotdb / user chatbot_user)

# 2. Rasa + Action Server
docker compose up -d rasa actions

# 3. Moteur FastAPI (natif, rechargement à chaud)
cd fastapi
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host localhost --port 8000

# 4. Stubs diagnostic (même venv)
uvicorn wallet_stub.main:app --port 3103
uvicorn user_stub.main:app --port 3104
```

Entraîner le modèle NLU :

```bash
docker compose run --rm rasa train
docker compose restart rasa
```

Interface de test : http://localhost:8000/chat

Procédure complète : [docs/10-deploiement.md](docs/10-deploiement.md).

## Tests

```bash
# NLU / stories Rasa
docker compose exec rasa rasa test nlu --out results
docker compose exec rasa rasa test

# Moteur FastAPI
cd fastapi && pytest tests/
```

## Limitations (état actuel)

- Environnement **développement** : pas d'auth utilisateur sur le périmètre assistant
- Mono-langue **français**
- Catalogue diagnostic encore restreint (stubs wallet/user) — bascule vers les vrais services Laravel dès que le contrat est implémenté côté microservices

Voir [docs/13-limitations.md](docs/13-limitations.md) et [docs/14-evolutions.md](docs/14-evolutions.md).
