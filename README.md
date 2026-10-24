# ngoni-ia-service

Microservice d'**assistance conversationnelle** de la plateforme NGONI : un agent qui comprend la demande d'un utilisateur, **agit** sur son dossier (diagnostic, réouverture, analyse de pièce d'identité), **sait s'arrêter** quand une décision doit rester humaine, et **passe la main** à un conseiller avec un dossier déjà instruit. Un espace d'administration permet de superviser l'activité et de régler le comportement de l'agent, chaque modification étant tracée.

> Principe : *le microservice métier décide, le moteur transporte, Rasa affiche*.

**Toute la pile tourne sous Docker** : une seule commande, `docker compose up -d --build`, lance la base de données, les modèles d'IA, le moteur, les services, Rasa et l'interface web.

---

## Sommaire

1. [Fonctionnalités](#fonctionnalités)
2. [Architecture](#architecture)
3. [Prérequis](#prérequis)
4. [Démarrage rapide](#démarrage-rapide)
5. [Adresses utiles](#adresses-utiles)
6. [Ce qui se passe au premier lancement](#ce-qui-se-passe-au-premier-lancement)
7. [Configuration (`.env`)](#configuration-env)
8. [Base de données](#base-de-données)
9. [Modèles d'IA](#modèles-dia)
10. [Commandes courantes](#commandes-courantes)
11. [Démonstration vidéo](#démonstration-vidéo)
12. [API](#api)
13. [Dépannage](#dépannage)
14. [Structure du dépôt](#structure-du-dépôt)
15. [Limitations](#limitations)

---

## Fonctionnalités

| Domaine | Ce que fait le service |
|---|---|
| **Compréhension** | Classification d'intention par un LLM local (`qwen3:1.7b` via Model) intégré à Rasa, avec repli vers un conseiller sous un seuil de confiance réglable **à chaud**. |
| **FAQ** | Recherche sémantique par embeddings (`qwen3-embedding:0.6b`, 1024 dimensions, `pgvector`), résistante aux fautes et aux reformulations. |
| **Diagnostic** | Interroge les services métier (`wallet`, `user`) via un contrat HTTP versionné (*Capability Registry*) : refus KYC, retraits bloqués, accès compte… |
| **Pièces d'identité** | Pré-vérification (netteté, type, lisibilité, validité) et extraction des champs par OCR (`rapidocr`). |
| **Escalade** | Ticket `CMP-…` et file de prise en charge humaine : le conseiller reçoit un résumé, la chronologie et les champs extraits. |
| **Supervision** | Tableau de bord (volumes, tickets, temps de réponse, intentions), paramètres du moteur avec identité exigée et historique des modifications. |
| **Feedback** | Notation des réponses, suggestions et plaintes. |

---

## Architecture

```
                    Navigateur  ──►  http://localhost:5173
                                         │
                                ┌────────┴─────────┐
                                │  frontend (nginx) │   /rasa/*   → rasa:5005
                                └────────┬─────────┘   /engine/* → fastapi:8000
                     ┌───────────────────┴───────────────────┐
                     ▼                                       ▼
              ┌─────────────┐   actions   ┌──────────┐   ┌────────────────┐
              │ rasa  :5005 │ ──────────► │ actions  │──►│ fastapi  :8000 │
              │ NLU + Core  │             │  :5055   │   │ moteur métier  │
              └──────┬──────┘             └──────────┘   └───┬───────┬────┘
                     │  classification (LLM)                 │       │  diagnostic
                     ▼                    embeddings          │       ▼
              ┌─────────────┐ ◄───────────────────────────────┘  ┌───────────────────────┐
              │ model      │                                      │ wallet_service  :3103    │
              │ qwen3:1.7b  │                                      │ user_service    :3104    │
              │ qwen3-emb.  │                                      └──────────┬────────────┘
              └─────────────┘                                                 │
                     ┌────────────────────────────────────────────────────────┘
                     ▼
              ┌──────────────────────────────┐
              │ postgres (PostgreSQL 17 +    │  FAQ, tickets, conversations,
              │ pgvector)  :5432 (hôte 5433) │  réglages, historique Rasa, KYC
              └──────────────────────────────┘
```

| Service | Image | Port hôte | Rôle |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` | 5433 | Base `chatbotdb`, volume persistant `pgdata` |
| `model` | `model/model:0.40.8` | — (interne) | LLM de classification et modèle d'embeddings, volume `model` |
| `model-init` | `model/model:0.40.8` | — | Télécharge les deux modèles au premier lancement, puis s'arrête |
| `prechauffage` | même image que `fastapi` | — | Charge le LLM et son prompt une fois Rasa prêt, puis s'arrête |
| `fastapi` | construit depuis `fastapi/` | 8000 | Moteur : FAQ, diagnostic, réclamations, conversations, administration |
| `wallet_service` | même image que `fastapi` | 3103 | Simule le service portefeuille (contrat diagnostic) |
| `user_service` | même image que `fastapi` | 3104 | Simule le service utilisateurs (KYC, compte) |
| `rasa` | construit depuis `rasa/` | 5005 | Dialogue (Rasa 3.6) et NLU |
| `actions` | construit depuis `rasa/actions/` | 5055 | Serveur d'actions Rasa |
| `frontend` | construit depuis `frontend/` | 5173 | Interface web (React + Vite), servie par nginx |
| `pgadmin` | `dpage/pgadmin4` | 5050 | Optionnel (profil `outils`) |

Entre conteneurs, chaque service se joint par son **nom** (`http://fastapi:8000`, `http://model:11434`…).

Documentation détaillée : [`docs/`](docs/README.md) · flux complet d'un message : [`docs/rapport-fonctionnement/`](docs/rapport-fonctionnement/00-index.md).

---

## Prérequis

- **Docker Desktop** (Windows / macOS) ou Docker Engine + Compose v2 (Linux).
- Mémoire allouée à Docker : **8 Go minimum** (le LLM, Rasa et le moteur tournent ensemble) ; 4 cœurs ou plus.
- Disque : **~25 Go libres** (images ~17 Go, dont 8 Go pour l'image officielle de Model ; modèles 2 Go ; base 0,2 Go).
- **Connexion Internet au premier lancement** (images Docker, dépendances, ~2 Go de modèles Model).
- Aucun GPU requis : tout tourne sur CPU (réponses plus lentes, voir [Dépannage](#dépannage)).

Rien d'autre n'est à installer : ni Python, ni Node, ni PostgreSQL, ni Model.

---

## Démarrage rapide

> **Nouveau PC, en un double-clic** : voir [installation/README.md](installation/README.md). `PREPARER-TRANSFERT.cmd` sur l'ancien PC, puis `INSTALLER.cmd` sur le nouveau : il installe Docker, clone le dépôt, restaure la base et les volumes, et lance tout.

```bash
# 1. Configuration
cp .env.example .env          # Windows : copy .env.example .env
#    puis éditer .env : au minimum POSTGRES_PASSWORD et APP_DB_PASSWORD
#    (lettres et chiffres uniquement)

# 2. (Recommandé) Données existantes : placer l'export de la base ici
#    docker/postgres/chatbotdb.dump      — voir « Base de données »

# 3. Lancer toute la pile
docker compose up -d --build

# 4. Suivre le démarrage (Ctrl+C pour quitter l'affichage, la pile continue)
docker compose ps
docker compose logs -f prechauffage
```

La pile est prête quand le préchauffage affiche **`prechauffage termine`** (`docker compose ps -a` : `prechauffage` en `Exited (0)`). Ouvrir ensuite **http://localhost:5173**.

---

## Adresses utiles

| Quoi | Adresse |
|---|---|
| Chat client | http://localhost:5173/#/chat |
| Espace conseiller | http://localhost:5173/#/agent/live |
| Administration (tableau de bord) | http://localhost:5173/#/admin |
| Paramètres du moteur | http://localhost:5173/#/admin/settings |
| Démonstration rejouée | http://localhost:5173/?demo=1#/chat |
| API FastAPI (Swagger) | http://localhost:8000/docs |
| Statut Rasa | http://localhost:5005/status |
| Services (Swagger) | http://localhost:3103/docs · http://localhost:3104/docs |
| PostgreSQL depuis l'hôte | `localhost:5433`, base `chatbotdb`, compte `chatbot_user` |
| pgAdmin (optionnel) | http://localhost:5050 |

---

## Ce qui se passe au premier lancement

1. **Construction des images** `fastapi` (PyTorch CPU inclus), `rasa`, `actions`, `frontend` — 10 à 20 min selon la connexion.
2. **`postgres`** initialise le volume `pgdata` : crée le compte `chatbot_user`, la base `chatbotdb`, les extensions `vector`, `pgcrypto`, `uuid-ossp`, puis **restaure `docker/postgres/chatbotdb.dump`** s'il est présent ([détails](#base-de-données)).
3. **`model-init`** télécharge `qwen3:1.7b` et `qwen3-embedding:0.6b` (~2 Go) dans le volume `model`, puis s'arrête (état `exited (0)` : c'est normal).
4. **`fastapi`**, les services, **`rasa`** et **`actions`** démarrent ; Rasa charge le modèle le plus récent de `rasa/models/`.
5. **`frontend`** sert l'interface sur le port 5173.
6. **`prechauffage`** envoie quelques messages au classifieur : sans GPU, le tout premier appel charge le LLM et lit tout son prompt (2 à 5 min, quelques essais en `nlu_fallback` sont normaux). Il affiche `prechauffage termine` puis s'arrête.

Les lancements suivants (`docker compose up -d`) prennent quelques minutes au plus : images, base et modèles sont conservés, seul le préchauffage est rejoué.

> **Temps de réponse sans GPU** : 10 à 35 s par message une fois le préchauffage terminé. Le LLM reste ensuite en mémoire en permanence.

---

## Configuration (`.env`)

Un seul fichier, à la racine, lu par `docker-compose.yml`. Modèle : [`.env.example`](.env.example). **Ne jamais le commiter.**

| Variable | Défaut | Rôle |
|---|---|---|
| `POSTGRES_PASSWORD` | — | Superutilisateur `postgres` du conteneur |
| `APP_DB_USER` / `APP_DB_PASSWORD` / `APP_DB_NAME` | `chatbot_user` / — / `chatbotdb` | Compte utilisé par FastAPI, les services et Rasa. **Mot de passe : lettres et chiffres uniquement** (il est inséré dans l'URL de connexion). |
| `POSTGRES_HOST_PORT` | `5433` | Port PostgreSQL publié sur l'hôte |
| `ADMIN_INTERNAL_SECRET` | `dev-admin-secret-change-me` | Secret des routes d'administration. Il est figé dans l'interface **au build** : après modification, `docker compose up -d --build frontend fastapi`. |
| `SERVICES_INTERNAL_SECRET` | `test-secret` | Secret partagé entre FastAPI et les services |
| `REGISTRY_POLL_INTERVAL_SECONDS` | `300` | Rafraîchissement du catalogue de diagnostic |
| `NLU_CONTEXT_ENABLED` | `false` | Mémoire de conversation dans le classifieur (lent sans GPU) |
| `LLM_REPLY_ENABLED` | `false` | Réponse de repli générée par le LLM (~30 s de plus sans GPU) |
| `SUPPORT_CONTACT_EMAIL` / `SUPPORT_CONTACT_PHONE` | — | Coordonnées affichées par l'agent |
| `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` | — | Connexion à pgAdmin |

Les URL entre services sont fixées dans `docker-compose.yml` et n'ont pas à être modifiées.

---

## Base de données

### Persistance

Les données vivent dans le volume Docker **`pgdata`**. Elles survivent à `docker compose down`, aux redémarrages et aux reconstructions d'images. **Seul `docker compose down -v` les efface.**

### Restauration initiale

Au **tout premier** démarrage (volume vide), le script [`docker/postgres/initdb/01-restaurer-chatbotdb.sh`](docker/postgres/initdb/01-restaurer-chatbotdb.sh) restaure `docker/postgres/chatbotdb.dump` s'il existe. Sans ce fichier, la base est créée **vide**.

Le fichier `*.dump` est ignoré par Git : il contient des données réelles (conversations, données KYC).

### Sauvegarder la base

```bash
docker compose exec postgres pg_dump -U postgres -d chatbotdb -Fc -Z 9 -f /tmp/chatbotdb.dump
docker compose cp postgres:/tmp/chatbotdb.dump docker/postgres/chatbotdb.dump
```

Ce fichier est celui à transporter vers un autre poste : placé dans `docker/postgres/`, il est restauré automatiquement au premier `docker compose up`.

### Repartir d'une base propre

```bash
docker compose down -v                  # supprime pgdata (et le volume model)
docker compose up -d                    # réinitialise depuis docker/postgres/chatbotdb.dump
```

### Accès direct

```bash
docker compose exec postgres psql -U chatbot_user -d chatbotdb
```

Depuis l'hôte (DBeaver, pgAdmin…) : `localhost:5433`.

### Contenu

| Schéma | Contenu |
|---|---|
| `ia` | FAQ, conversations et messages, réclamations, diagnostics, réglages du moteur et leur historique, conseillers, audit des actions de l'agent |
| `public` | Historique des conversations Rasa (`events`) |
| `users` | Comptes et dossiers KYC (lus par `user_service`) |
| `wallet_service` | Portefeuilles et retraits simulés (`wallet_service`) |

Modèle de données : [`docs/15-modele-donnees.md`](docs/15-modele-donnees.md).

---

## Modèles d'IA

### Model

Les deux modèles sont téléchargés une fois par `model-init` dans le volume `model` :

| Modèle | Usage |
|---|---|
| `qwen3:1.7b` | Classification d'intention (composant Rasa `QwenIntentClassifier`), réponses de repli optionnelles |
| `qwen3-embedding:0.6b` | Embeddings de la FAQ et du diagnostic (1024 dimensions) |

### Modèle Rasa

Rasa charge le modèle le plus récent de [`rasa/models/`](rasa/models/) (monté dans le conteneur). Après une modification de `rasa/data/`, `rasa/domain.yml` ou `rasa/config.yml` :

```bash
docker compose run --rm rasa python -m rasa train --out models
docker compose restart rasa
```

### Seuils réglables à chaud

Dans **Administration → Paramètres**, les seuils marqués « en direct » (confiance minimale et écart d'ambiguïté du classifieur) s'appliquent au moteur en quelques secondes, sans redémarrage : Rasa les relit via `GET /settings/engine` ([`rasa/components/dynamic_fallback_classifier.py`](rasa/components/dynamic_fallback_classifier.py)). Chaque modification exige l'identité de l'administrateur et apparaît dans l'historique.

### Revenir aux classifieurs BGE (optionnel)

Le cache Hugging Face du conteneur Rasa (`rasa/.cache/huggingface`, dont `BAAI/bge-m3`) et les classifieurs BGE entraînés (`trash/nlu_bge/model/versions`, à replacer dans `rasa/nlu_bge/model/versions`) sont conservés hors Git pour une éventuelle bascule.

---

## Commandes courantes

```bash
docker compose up -d                      # démarrer
docker compose down                       # arrêter (données conservées)
docker compose ps                         # état des services
docker compose logs -f fastapi rasa       # journaux en continu
docker compose restart rasa               # redémarrer un service
docker compose up -d --build fastapi      # reconstruire un service après modification du code
docker compose up -d --build              # tout reconstruire

# Tests du moteur (146 tests ; contracts/ est monté car les tests de contrat le lisent)
docker compose run --rm --no-deps -v ./contracts:/contracts:ro fastapi pytest tests/ -q
docker compose run --rm rasa python -m rasa test nlu --out results

# Outil optionnel
docker compose --profile outils up -d pgadmin
```

Le code de `rasa/` et `rasa/actions/` est monté dans les conteneurs : un `docker compose restart rasa actions` suffit après une modification. Pour `fastapi/` et `frontend/`, reconstruire l'image (`--build`).

---

## Démonstration vidéo

L'interface embarque un **mode démonstration rejoué** (scénario KYC complet : chat client → espace conseiller → supervision), déclenché par l'adresse :

- http://localhost:5173/?demo=1#/chat — l'envoi de la pièce d'identité attend une action manuelle ;
- http://localhost:5173/?demo=1&auto=1#/chat — entièrement automatique (y compris la fenêtre de sélection de fichier).

Enregistrer la vidéo (outil de poste de travail, **hors Docker** : nécessite Node 22+, Google Chrome et ffmpeg sur l'hôte, la pile Docker étant lancée) :

```bash
node scripts/enregistrer_demo_auto.mjs --sortie demo/demo-ngoni.mp4
```

Chrome tourne en mode invisible : l'écran reste libre pendant l'enregistrement.

---

## API

Référence complète : Swagger sur http://localhost:8000/docs et [`docs/06-api-reference.md`](docs/06-api-reference.md).

| Domaine | Routes principales |
|---|---|
| Chat de test | `POST /api/parse` · `POST /api/chat` |
| FAQ | `GET /faq/` · `POST /faq/search` · `GET /faq/suggestions` |
| Diagnostic | `GET /diagnostic/capabilities` · `POST /diagnostic/resolve` (en-tête `X-User-ID`) · `POST /diagnostic/escalate` |
| Réclamations | `POST /tickets/create` · `GET /complaints/{ticket_id}` |
| Feedback | `POST /feedback` · `POST /feedback/ratings` |
| Prise en charge humaine | `POST /conversations/escalate` · `GET /conversations/{id}/updates` · `POST /admin/conversations/{id}/assign` · `POST /admin/conversations/{id}/messages` |
| Supervision | `GET /admin/dashboard/summary` · `GET /admin/dashboard/intent-distribution` · `GET /admin/system/health` |
| Paramètres du moteur | `GET /admin/settings/parameters` · `PATCH /admin/settings/parameters/{id}` · `GET /admin/settings/parameters/history` · `GET /settings/engine` (lecture seule, utilisé par Rasa) |
| Embeddings | `POST /embeddings/query` · `POST /embeddings/query/batch` |
| Rasa (`:5005`) | `POST /webhooks/rest/webhook` · `POST /model/parse` · `GET /status` |

Les routes `/admin/*` exigent l'en-tête `X-Internal-Secret` (= `ADMIN_INTERNAL_SECRET`).

### Contrat diagnostic

Tout service diagnosticable expose `GET /diagnostic/manifest` et `POST /diagnostic/{problem_id}` (en-têtes `X-Internal-Secret`, `X-Request-ID`). Schémas : [`contracts/diagnostic/`](contracts/diagnostic/). Les services `wallet_service` / `user_service` implémentent ce contrat ; pour brancher les vrais services, faire pointer `WALLET_SERVICE_BASE_URL` / `USER_SERVICE_BASE_URL` (service `fastapi` dans `docker-compose.yml`) vers eux.

---

## Dépannage

| Symptôme | Cause et solution |
|---|---|
| `port is already allocated` | Un programme local occupe le port (PostgreSQL Windows, ancien lancement natif…). Arrêter ce programme, ou changer le port publié (`POSTGRES_HOST_PORT`, ou la partie gauche de `ports:` dans `docker-compose.yml`). |
| `fastapi` / `rasa` restent en `starting` au premier lancement | Normal tant qu'`model-init` télécharge les modèles : `docker compose logs -f model-init`. |
| L'agent répond « Je n'ai pas bien saisi votre demande » à tout | Le préchauffage n'est pas terminé (`docker compose logs prechauffage`), ou le classifieur dépasse son délai de 90 s : vérifier la mémoire et les cœurs alloués à Docker, puis `docker compose up -d prechauffage`. |
| Tests de contrat en échec sous Git Bash | Git Bash réécrit `/contracts` en chemin Windows : préfixer la commande par `MSYS_NO_PATHCONV=1`, ou la lancer depuis PowerShell / cmd. |
| Pages d'administration en erreur 401 | `ADMIN_INTERNAL_SECRET` a changé sans reconstruire l'interface : `docker compose up -d --build frontend fastapi`. |
| Base vide après le premier lancement | `docker/postgres/chatbotdb.dump` était absent. Le placer, puis `docker compose down -v && docker compose up -d`. ⚠ `-v` efface les données existantes. |
| `postgres` en échec au premier lancement | Lire `docker compose logs postgres` : la restauration s'arrête à la première erreur. Corriger, puis `docker compose down -v` et relancer. |
| Rasa : « No model found » | `rasa/models/` est vide : entraîner (voir [Modèle Rasa](#modèle-rasa)). |
| Modification du code non prise en compte | `fastapi` et `frontend` sont des images : `docker compose up -d --build <service>`. |

---

## Structure du dépôt

```
ngoni-ia-service/
├── docker-compose.yml        # toute la pile
├── .env.example              # modèle de configuration
├── docker/postgres/          # restauration initiale de la base (+ chatbotdb.dump, hors Git)
├── fastapi/                  # moteur métier + services wallet/user (une seule image)
│   ├── app/domains/          # faq, diagnostic, complaints, conversations, settings, stats…
│   ├── wallet_service/ user_service/
│   ├── migrations/ seeds/    # historique du schéma
│   └── tests/
├── rasa/                     # dialogue : config.yml, domain.yml, data/, models/
│   ├── components/           # classifieur LLM, repli à seuils dynamiques
│   └── actions/              # serveur d'actions
├── frontend/                 # interface React (Vite) + nginx.conf
├── contracts/diagnostic/     # contrat versionné des services diagnosticables
├── scripts/                  # enregistrement de la démonstration vidéo
├── demo/                     # vidéos et pièces de la démonstration
└── docs/                     # documentation détaillée
```

---

## Limitations

- Environnement de **développement** : pas d'authentification utilisateur sur le périmètre assistant ; secrets par défaut à remplacer.
- **Français** uniquement.
- **CPU uniquement** : la classification par LLM prend plusieurs secondes par message sans GPU.
- Diagnostic branché sur des **services** `wallet` / `user` en attendant que les services réels implémentent le contrat.

Voir [`docs/13-limitations.md`](docs/13-limitations.md) et [`docs/14-evolutions.md`](docs/14-evolutions.md).
