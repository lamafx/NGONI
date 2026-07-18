← [Sommaire](README.md) | [8. Pipeline de traitement](08-pipeline-traitement.md)

# 9. Configuration

## 9.1 Variables d'environnement

Chaque processus lit son propre fichier `.env`, jamais commité (voir
`.gitignore`) — seuls les `.env.example` sont versionnés et servent de
modèle.

### `fastapi/.env` (moteur NGONI + stubs, mêmes venv/process family)

| Variable | Exemple | Rôle |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://chatbot_user:changeme@127.0.0.1:5432/chatbotdb` | Connexion SQLAlchemy vers PostgreSQL |
| `RASA_PARSE_URL` | `http://127.0.0.1:5005/model/parse` | Utilisé par `/api/parse` (interface de test) |
| `RASA_WEBHOOK_URL` | `http://127.0.0.1:5005/webhooks/rest/webhook` | Utilisé par `/api/chat` |
| `WALLET_SERVICE_INTERNAL_SECRET` | `changeme` | Secret envoyé en `X-Internal-Secret` vers `wallet-service`/`wallet_stub` |
| `USER_SERVICE_INTERNAL_SECRET` | `changeme` | Idem pour `user-service`/`user_stub` |
| `REGISTRY_POLL_INTERVAL_SECONDS` | `300` (30 en dev pour itérer plus vite) | Fréquence de rafraîchissement du Capability Registry |
| `WALLET_SERVICE_BASE_URL` | `http://127.0.0.1:3103/api/v1` (défaut dans `services_registry.yaml`) | URL du service wallet (stub ou réel) |
| `USER_SERVICE_BASE_URL` | `http://127.0.0.1:3104/api/v1` (défaut) | URL du service user (stub ou réel) |
| `WALLET_STUB_INTERNAL_SECRET` | `test-secret` | Côté `wallet_stub` : secret attendu en entrée, doit correspondre à `WALLET_SERVICE_INTERNAL_SECRET` côté moteur |
| `USER_STUB_INTERNAL_SECRET` | `test-secret` | Idem côté `user_stub` |

### `rasa/.env` (conteneur `rasa`)

| Variable | Exemple | Rôle |
|---|---|---|
| `RASA_MODEL_SERVER` | `http://127.0.0.1:5005` | — |
| `RASA_ENABLE_API` | `true` | Active l'API REST (`/model/parse`, `/webhooks/*`) |
| `TRACKER_DB_HOST` | `host.docker.internal` | Hôte PostgreSQL du tracker store, résolu depuis le conteneur |
| `TRACKER_DB_PORT` | `5432` | — |
| `TRACKER_DB_USER` / `TRACKER_DB_PASSWORD` / `TRACKER_DB_NAME` | `chatbot_user` / `...` / `chatbotdb` | Identifiants de connexion, mêmes que le moteur FastAPI |

> ⚠️ Dans `endpoints.yml`, les valeurs `${VAR}` de `tracker_store` ne doivent
> **jamais** être mises entre guillemets : le résolveur d'environnement de
> Rasa ne s'applique qu'aux scalaires YAML non quotés — une valeur entre
> guillemets court-circuite la résolution et reste littéralement `${VAR}`.

### `rasa/actions/.env` (conteneur `actions`)

| Variable | Exemple | Rôle |
|---|---|---|
| `FAQ_SERVICE_URL` | `http://host.docker.internal:8000/faq/search` | — |
| `FAQ_SUGGESTIONS_SERVICE_URL` | `http://host.docker.internal:8000/faq/suggestions` | — |
| `TICKET_SERVICE_URL` | `http://host.docker.internal:8000/tickets/create` | — |
| `FEEDBACK_SERVICE_URL` | `http://host.docker.internal:8000/feedback` | — |
| `DIAGNOSTIC_SERVICE_URL` | `http://host.docker.internal:8000/diagnostic/resolve` | — |
| `DIAGNOSTIC_CAPABILITIES_URL` | `http://host.docker.internal:8000/diagnostic/capabilities` | — |
| `EMBEDDING_SERVICE_URL` | `http://host.docker.internal:8000/embeddings/query` | — |
| `EMBEDDING_BATCH_SERVICE_URL` | `http://host.docker.internal:8000/embeddings/query/batch` | — |
| `SUPPORT_CONTACT_EMAIL` / `SUPPORT_CONTACT_PHONE` | `support@ngoni.com` / `+225 00 00 00 00` | Affichés dans les messages d'escalade |

> `host.docker.internal` : le conteneur `actions` appelle le moteur FastAPI
> qui tourne **nativement sur l'hôte** (pas en Docker, voir
> [10.2](10-deploiement.md#102-ce-qui-tourne-en-conteneur-vs-nativement-sur-lhôte)) —
> c'est le nom DNS spécial fourni par Docker Desktop pour atteindre l'hôte
> depuis un conteneur.

## 9.2 Fichiers de configuration Rasa

| Fichier | Contenu |
|---|---|
| `config.yml` | Pipeline NLU + policies Core (voir [7.2](07-integration-ia.md#72-modèle-nlu-diet-classifier)) |
| `domain.yml` | Intentions, entités, slots, formulaires, réponses `utter_*` |
| `credentials.yml` | Canaux activés (`rest` uniquement dans ce projet) |
| `endpoints.yml` | URL de l'action server, configuration du tracker store |

## 9.3 `services_registry.yaml` — ajouter un microservice diagnosticable

```yaml
services:
  - name: wallet
    base_url_env: WALLET_SERVICE_BASE_URL
    base_url_default: http://localhost:3103/api/v1
    internal_secret_env: WALLET_SERVICE_INTERNAL_SECRET
```

Ajouter un service = ajouter une entrée ici, **sans modification de code
Python** et **sans redémarrage** du moteur — relu à chaque cycle de
`poll_forever()`. Le fichier déclare uniquement le **nom** des variables
d'environnement à lire, jamais la valeur elle-même ; `base_url_default` sert
de repli pour le développement local quand la variable n'est pas définie.
Le contenu du manifeste (quels problèmes, quels champs) n'est jamais dupliqué
ici — récupéré réellement via `GET {base_url}/diagnostic/manifest` à chaque
rafraîchissement. Voir [2.4](02-architecture.md#24-le-pattern-capability-registry).

## 9.4 Configuration base de données

- **`fastapi/init_db.sql`** : schéma initial (tables `core.faq_items`,
  `complaints.complaints`...), exécuté automatiquement par l'image Postgres
  Docker au premier démarrage (`docker-entrypoint-initdb.d`) — sans effet si
  Postgres tourne nativement et que la base existe déjà.
- **`fastapi/migrations/`** : scripts SQL incrémentaux à appliquer
  manuellement dans l'ordre (`0001_e5_base_upgrade.sql`,
  `0002_feedback_table.sql`, `0003_response_ratings_table.sql`,
  `0004_check_constraints.sql`, `0005_feedback_ticket_created_by.sql`) — voir
  [11. Maintenance](11-maintenance.md) pour la procédure d'application.
- Pour le schéma résultant (tables, colonnes, types, `pgvector`), voir
  [15. Modèle de données](15-modele-donnees.md) — ce chapitre-ci ne couvre
  que la configuration/le processus de migration, pas la structure finale.

## 9.5 Paramètres modifiables sans redéploiement

| Paramètre | Emplacement | Effet d'un changement |
|---|---|---|
| `REGISTRY_POLL_INTERVAL_SECONDS` | variable d'environnement (moteur) | Fréquence de découverte des nouveaux services/problèmes diagnosticables |
| `DEFAULT_THRESHOLD` | `app/domains/faq/service.py` (constante, nécessite un redéploiement du moteur) | Seuil de correspondance FAQ |
| `MIN_EMBEDDING_SIMILARITY`, `KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY`, `CLASSIFICATION_RELATIVE_MARGIN`, `TOPIC_SWITCH_RELATIVE_MARGIN` | `rasa/actions/diagnostic.py` (constantes, nécessite un redéploiement de l'action server) | Sensibilité de la classification de problème diagnostiqué — voir [7.5](07-integration-ia.md#choix-du-modèle--historique-et-calibration-empirique) |
| `CAPABILITIES_CACHE_TTL_SECONDS` | `rasa/actions/diagnostic.py` | Délai maximal avant qu'un changement de manifeste soit vu côté bot |
| `MAX_MESSAGE_LENGTH`, `MAX_FIELD_ANSWER_LENGTH` | `feedback/service.py`, `rasa/actions/diagnostic.py` | Protection contre l'épuisement de ressources sur des champs libres |

> Les constantes ci-dessus sont du code, pas des variables d'environnement :
> les changer implique un redéploiement du composant concerné, mais **pas**
> une modification d'architecture. Elles sont documentées ici car ce sont
> les leviers de réglage les plus fréquemment ajustés en pratique (voir les
> commentaires de calibration empirique dans le code source).

## 9.6 Gestion des secrets

Les secrets (`WALLET_SERVICE_INTERNAL_SECRET`, `USER_SERVICE_INTERNAL_SECRET`,
identifiants PostgreSQL) sont actuellement de simples variables
d'environnement en clair dans des fichiers `.env` non commités — aucun
coffre-fort de secrets. Voir [13. Limitations actuelles](13-limitations.md)
pour l'état des lieux complet et [14. Perspectives d'évolution](14-evolutions.md)
pour les pistes de mise en conformité production.

---

Suite : [10. Déploiement](10-deploiement.md)
