← [Sommaire](README.md) | [3. Taxonomie du projet](03-taxonomie.md)

# 4. Architecture des services

## 4.1 Service Rasa (NLU + Core)

**Port** : `5005`. **Conteneur** : `rasa` (Docker).

Rôle : transformer un message texte en intention + entités (NLU), puis
décider de la prochaine action à exécuter en fonction de l'état de la
conversation (Core). Pipeline NLU (voir [7.2](07-integration-ia.md#72-modèle-nlu-diet-classifier)
pour le détail) :

`WhitespaceTokenizer → RegexFeaturizer → LexicalSyntacticFeaturizer → CountVectorsFeaturizer (mots) → CountVectorsFeaturizer (char_wb) → DIETClassifier → EntitySynonymMapper → ResponseSelector → VocabularyCoverageGuard (composant personnalisé) → FallbackClassifier`

Policies Core : `MemoizationPolicy`, `RulePolicy` (gère nativement le
fallback), `UnexpecTEDIntentPolicy`, `TEDPolicy`.

Persistance : le tracker store est configuré en SQL (PostgreSQL, même
instance que le moteur FastAPI) — sans cela, tout l'historique de
conversation serait perdu à chaque redémarrage du conteneur.

## 4.2 Service Actions

**Port** : `5055`. **Conteneur** : `actions` (Docker), image construite à
partir de `rasa/actions/Dockerfile`.

Processus Python séparé du serveur Rasa lui-même, exposant un unique
endpoint `POST /webhook` appelé par Rasa Core. C'est **le seul** composant
Rasa qui parle HTTP au moteur FastAPI — Rasa Core ne connaît jamais FastAPI
directement. Séparé du processus Rasa pour deux raisons : isoler le code
métier (et ses dépendances propres) du runtime Rasa, et permettre de
redéployer/recharger les actions sans réentraîner ni redémarrer le modèle
NLU/Core.

Voir [3.2.1](03-taxonomie.md#321-rasaactions--serveur-dactions) pour
l'inventaire des actions par fichier.

## 4.3 Moteur NGONI (FastAPI) — domaine par domaine

**Port** : `8000`. **Processus natif** sur l'hôte (voir [10.2](10-deploiement.md#102-ce-qui-tourne-en-conteneur-vs-nativement-sur-lhôte)).

| Domaine | Responsabilité | Dépend de |
|---|---|---|
| **FAQ** (`app/domains/faq`) | CRUD des questions/réponses, recherche sémantique (`find_best_answer`), suggestions groupées par catégorie. | Service d'embeddings partagé |
| **Diagnostic** (`app/domains/diagnostic`) | Capability Registry, pipeline de résolution générique, résilience (circuit breaker), audit. Voir [3.4](03-taxonomie.md#34-fastapiappdomainsdiagnostic-en-détail) pour le détail interne. | Service d'embeddings, `wallet-service`/`user-service` (ou services), domaine Complaints (pour l'escalade auto) |
| **Complaints** (`app/domains/complaints`) | Création et consultation de tickets (réclamations, escalades diagnostiques, escalades feedback). | — |
| **Feedback** (`app/domains/feedback`) | Suggestions, plaintes, notation des réponses (utile/pas utile). Peut créer un ticket associé selon le type. | Domaine Complaints |
| **Embeddings** (`app/shared/embeddings`) | Charge **une seule fois** par process le modèle `intfloat/multilingual-e5-base` (singleton) et l'expose via `/embeddings/query[/batch]`, réutilisé par le domaine FAQ, le Capability Registry et l'action server Rasa. | — |

Le moteur expose aussi une interface de test intégrée (`/`, `/chat`,
`/api/parse`, `/api/chat`) qui proxifie Rasa — pratique pour tester le bot
sans dépendre d'un frontend mobile/web (voir [6. Référence API §1.6](06-api-reference.md)).

## 4.4 Microservices consommés par le Diagnostic Engine

En développement, le Diagnostic Engine s'appuie sur deux **services** FastAPI
indépendants (`fastapi/wallet_service`, `fastapi/user_service`) qui simulent le
comportement des vrais microservices `ngoni-wallet-service` (Laravel/PHP) et
`ngoni-user-service` (Laravel/PHP), en implémentant exactement le même
contrat (`/diagnostic/manifest`, `/diagnostic/{problem_id}`). Cela permet de
développer et tester le moteur de diagnostic sans dépendre de la
disponibilité ni de l'état des vraies bases de données wallet/user.

| | Service de développement | Service réel (hors périmètre détaillé de ce document) |
|---|---|---|
| Wallet | `fastapi/wallet_service` — port `3103` | `ngoni-wallet-service` (Laravel, gRPC) |
| User | `fastapi/user_service` — port `3104` | `ngoni-user-service` (Laravel, gRPC) |

Le contrat étant indépendant du langage (JSON Schema autonome, voir
[3.6](03-taxonomie.md#36-contractsdiagnosticv1--contrat-versionné)), faire
basculer le Diagnostic Engine du service vers le service réel ne nécessite
qu'un changement de configuration (`WALLET_SERVICE_BASE_URL`,
`USER_SERVICE_BASE_URL` dans `services_registry.yaml` / variables
d'environnement) — voir [9. Configuration](09-configuration.md) — dès lors
que le service réel implémente lui-même ce contrat (voir l'état
d'implémentation documenté en §8 de `contracts/diagnostic/README.md`).

## 4.5 Stockage

**PostgreSQL 15** (`postgres:15-alpine` en Docker en théorie, instance native
en pratique dans ce projet — voir [10.2](10-deploiement.md)), base unique
partagée par :

- le moteur FastAPI (schémas `core` — FAQ, `complaints` — tickets, tables
  `feedback`, `response_ratings`, `diagnostic_audit_log`) ;
- le tracker store Rasa (table `events`, créée automatiquement par Rasa au
  premier démarrage).

**pgAdmin** (`dpage/pgadmin4`, port `5050`) : interface d'administration en
développement, jamais appelée par un composant applicatif.

Pour le détail des schémas, tables et types de données réels (dont
l'extension `pgvector` utilisée par le domaine FAQ), voir
[15. Modèle de données](15-modele-donnees.md).

## 4.6 Matrice des dépendances inter-services

| Appelant | Appelé | Protocole | Synchrone ? |
|---|---|---|---|
| Rasa Core | Action Server | HTTP (webhook Rasa SDK) | Oui |
| Action Server | Moteur FastAPI (`/faq/*`, `/diagnostic/*`, `/feedback*`, `/tickets/create`, `/embeddings/*`) | HTTP/JSON | Oui |
| Moteur FastAPI | `wallet-service` / `user-service` (ou services) — `/diagnostic/manifest`, `/diagnostic/{problem_id}` | HTTP/JSON | Oui |
| Moteur FastAPI | PostgreSQL | SQL (SQLAlchemy) | Oui |
| Rasa Core | PostgreSQL (tracker store) | SQL | Oui |
| Moteur FastAPI (interface de test `/api/chat`) | Rasa (`/model/parse`, `/webhooks/rest/webhook`) | HTTP/JSON | Oui |

Aucune communication asynchrone (file de messages, event bus) n'existe dans
ce périmètre : chaque appel est un aller-retour HTTP synchrone avec timeout,
protégé côté Diagnostic Engine par un disjoncteur (voir
[8. Pipeline de traitement](08-pipeline-traitement.md)).

---

Suite : [5. Communication entre les services](05-communication.md)
