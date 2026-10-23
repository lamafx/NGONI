← [Sommaire](README.md) | [2. Architecture globale](02-architecture.md)

# 3. Taxonomie du projet

Ce chapitre décrit l'organisation des dossiers du périmètre assistant
conversationnel. Seuls les fichiers pertinents pour la compréhension et la
maintenance sont commentés ; les artefacts générés (`__pycache__`, `.venv`,
`.rasa`, logs) sont omis.

## 3.1 Racine du dépôt

```
PFE/
├── rasa/                    # Bot conversationnel (NLU + Core + actions)
├── fastapi/                 # Moteur NGONI (FAQ, diagnostic, réclamations, feedback, embeddings)
├── contracts/diagnostic/    # Contrat versionné Diagnostic Engine <-> microservices
├── docs/                    # Cette documentation + docs/diagrams
├── ngoni-core-service/      # Microservice Node.js/Fastify (module FAQ admin, hors périmètre détaillé)
├── ngoni-admin-service/     # Microservice Node.js/Fastify (hors périmètre)
├── ngoni-user-service/      # Microservice Laravel/PHP (profils, KYC...) — hors périmètre détaillé
├── ngoni-wallet-service/    # Microservice Laravel/PHP (transactions, retraits...) — hors périmètre détaillé
├── docker-compose.yml       # Définit rasa, actions, postgres, pgadmin, fastapi (voir §10.2 sur l'usage réel)
├── utils.txt                # Aide-mémoire des commandes de lancement natif
└── readme.md                # Note de configuration ponctuelle (identifiants DB locaux)
```

> Les quatre services `ngoni-*` appartiennent à la plateforme NGONI au sens
> large ; seule leur interface avec l'assistant (contrat de diagnostic,
> module FAQ) est couverte par cette documentation — voir
> [1.5 Public visé](01-presentation.md#15-public-visé-par-ce-document).

## 3.2 `rasa/` — bot conversationnel

```
rasa/
├── config.yml            # Pipeline NLU + policies Core (voir 07-integration-ia.md)
├── domain.yml             # Intentions, entités, slots, réponses (utter_*), formulaires
├── credentials.yml        # Canaux activés (rest uniquement)
├── endpoints.yml           # URL de l'action server, tracker store SQL (Postgres partagé)
├── data/
│   ├── nlu.yml             # Exemples d'entraînement par intention
│   ├── stories.yml         # Parcours de conversation complets (entraînement Core)
│   └── rules.yml           # Règles déterministes (ex. toujours répondre X à l'intention Y)
├── components/
│   └── vocabulary_guard.py # Composant NLU personnalisé (garde-fou anti hors-vocabulaire)
├── actions/                 # Serveur d'actions personnalisé (processus séparé, voir 3.2.1)
├── models/                  # Modèles entraînés (.tar.gz), produits par `rasa train`
├── results/                  # Rapports d'évaluation NLU (`rasa test nlu`)
└── tests/
    ├── test_nlu.yml          # Cas de test NLU (intentions attendues)
    └── test_stories.yml      # Cas de test de parcours de dialogue
```

### 3.2.1 `rasa/actions/` — serveur d'actions

| Fichier | Rôle | Actions principales |
|---|---|---|
| `capabilities.py` | Décrit ce que l'agent sait faire, source unique réutilisée par le message d'accueil et `ask_capabilities`. | `ActionDescribeCapabilities` |
| `diagnostic.py` | Le plus volumineux : classification des messages contre le Capability Registry (embeddings + repli mots-clés + désambiguïsation), collecte des champs requis, appel du moteur, gestion du fallback et du hors-sujet. | `ActionRunDiagnosticStep`, `ActionDecideEscalation`, `ActionHandleNegation`, `ActionDefaultFallback`, `ActionOutOfScope` |
| `faq.py` | Recherche et navigation FAQ (recherche libre, parcours par catégorie). | `ActionFaqSearch`, `ActionBrowseFaq`, `ActionSelectFaqCategory`, `ActionSelectFaqQuestion` |
| `reclamation.py` | Formulaire guidé de réclamation, jusqu'à la création du ticket. | `ActionStartReclamation`, `ActionExtractReclamationEntities`, `ActionGenerateReclamationSummary`, `ActionRequestReclamationConfirmation`, `ActionCreateTicket`, `ActionCancelReclamation`, `ActionAskCancelClarification` |
| `feedback.py` | Suggestions, plaintes, notation des réponses. | `ActionStoreSuggestion`, `ActionAcknowledgeComplaint`, `ActionRecordResponseRating` |
| `greeting.py` | Message d'accueil contextualisé (heure du jour, mise en avant de la FAQ). | `ActionGreetWithTime` |
| `common.py` | Fonctions partagées entre modules (recherche FAQ interne, détection de répétition, seuils de fallback). | — (pas d'`Action`, utilitaires) |

## 3.3 `fastapi/app/` — moteur NGONI

```
fastapi/
├── app/
│   ├── main.py                # Point d'entrée FastAPI, montage des routers, démarrage/arrêt
│   ├── database.py            # Session SQLAlchemy, get_db()
│   ├── models.py               # Modèles hérités (diagnostic_records, route /diagnostic/search)
│   ├── domains/
│   │   ├── faq/                # Modèle, repository, service, router, schémas — FAQ
│   │   ├── diagnostic/          # Le domaine le plus complexe (voir 3.4)
│   │   ├── complaints/          # Tickets de réclamation/escalade
│   │   └── feedback/            # Suggestions, plaintes, notations de réponse
│   └── shared/
│       └── embeddings/          # Service d'embeddings partagé (singleton SentenceTransformer)
├── user_service/                  # Simulation locale de ngoni-user-service (voir 3.5)
├── wallet_service/                # Simulation locale de ngoni-wallet-service (voir 3.5)
├── migrations/                  # Scripts SQL incrémentaux (voir 09-configuration.md)
├── scripts/
│   └── reembed_faq.py           # Recalcule les embeddings FAQ après changement de modèle
├── tests/                       # Suite de tests pytest (voir 11-maintenance.md)
├── services_registry.yaml       # Registre déclaratif des microservices diagnosticables
├── init_db.sql                  # Schéma initial (tables core, complaints...)
├── requirements.txt
└── .env / .env.example
```

Chaque domaine sous `app/domains/` suit le même patron à quatre fichiers :
`models.py` (ORM SQLAlchemy), `repository.py` (accès données), `service.py`
(logique métier), `router.py` (endpoints FastAPI), `schemas.py` (Pydantic,
entrée/sortie API). Ce patron est la convention à suivre pour ajouter un
nouveau domaine (voir [11. Maintenance](11-maintenance.md)). Pour le schéma
PostgreSQL réel derrière chaque `models.py` (tables, types, pgvector), voir
[15. Modèle de données](15-modele-donnees.md).

## 3.4 `fastapi/app/domains/diagnostic/` en détail

Le domaine diagnostic ne suit pas exactement le patron à quatre fichiers
ci-dessus : sa complexité (orchestration multi-service, résilience,
traçabilité) justifie un découpage plus fin.

| Fichier | Rôle |
|---|---|
| `router.py` | Endpoints `/diagnostic/*` (`capabilities`, `resolve`, `escalate`, `debug/classify`, `search` hérité). |
| `pipeline.py` | `DiagnosticPipeline` — orchestration générique et sans logique métier : lookup, validation de complétude, invocation, résilience (voir [8. Pipeline de traitement](08-pipeline-traitement.md)). |
| `registry.py` | `CapabilityRegistry` — charge `services_registry.yaml`, interroge les manifestes, calcule les embeddings en lot, rafraîchissement périodique (voir [2.4](02-architecture.md#24-le-pattern-capability-registry)). |
| `adapter.py` | `HttpDiagnosticAdapter` — appelle réellement le microservice cible, porte le disjoncteur (circuit breaker) partagé entre requêtes. |
| `circuit_breaker.py` | Disjoncteur générique : ouvre après un nombre d'échecs consécutifs, protège les microservices en difficulté d'un afflux de requêtes. |
| `contracts.py` | Miroir Pydantic des schémas JSON de `contracts/diagnostic/v1/` (voir [3.6](#36-contractsdiagnosticv1--contrat-versionné)). |
| `escalation.py` | Relais générique vers la création de ticket (`escalate_to_ticket`), utilisé aussi bien par `/diagnostic/escalate` que par la résilience automatique de `/diagnostic/resolve`. |
| `audit_repository.py` | `DiagnosticAuditRepository` — trace chaque résolution (trace_id, latence, issue) à des fins d'audit/supervision. |
| `models.py` / `schemas.py` | Modèles hérités de la route `/diagnostic/search` (table `diagnostic_records`, non liée au Diagnostic Engine par manifeste). |

## 3.5 `fastapi/user_service/` et `fastapi/wallet_service/`

Deux applications FastAPI minimales, indépendantes du moteur principal,
utilisées en développement pour simuler `ngoni-user-service` et
`ngoni-wallet-service` sans dépendre des vrais services (ports `3104` et
`3103`). Structure miroir :

```
wallet_service/                       user_service/
├── main.py                        ├── main.py
├── db.py                          ├── db.py
├── security.py                    ├── security.py
├── outcomes.py                    ├── outcomes.py
└── diagnostic/                    └── diagnostic/
    ├── manifest.py  (catalogue        ├── manifest.py  (catalogue
    │  des problèmes déclarés)          │  des problèmes déclarés)
    ├── router.py    (GET manifest,     ├── router.py
    │  POST /diagnostic/{problème})     │
    ├── formatting.py                  ├── formatting.py
    └── services/                      └── services/
        ├── withdrawal.py                  ├── kyc.py
        ├── topup.py                       ├── account_status.py
        └── gift.py                        ├── compliance.py
                                            ├── deletion.py
                                            └── parental_consent.py
```

Chaque fichier sous `services/` porte la logique de résolution d'**un seul**
problème (ex. `withdrawal.py` décide `RESOLVED`/`ESCALATE`/`NEED_MORE_INFO`
pour `withdrawal_pending`) — c'est le point d'extension naturel pour ajouter
un problème diagnosticable simulé.

## 3.6 `contracts/diagnostic/v1/` — contrat versionné

```
contracts/diagnostic/
├── README.md                          # Source de vérité du contrat (portée, versionnement, sécurité)
└── v1/
    ├── capability-manifest.schema.json          # GET /diagnostic/manifest
    ├── client-request.schema.json                # POST /diagnostic/resolve (entrée)
    ├── service-invocation-request.schema.json    # Engine -> microservice
    ├── service-invocation-response.schema.json   # microservice -> Engine (RESOLVED/ESCALATE/NEED_MORE_INFO)
    └── examples/
        ├── valid/     # Un exemple conforme par schéma
        └── invalid/   # Cas volontairement non conformes, catalogués
```

Chaque schéma est autonome (aucun `$ref` inter-fichiers) pour rester
validable indépendamment côté Python (FastAPI) et côté PHP
(Laravel/wallet-service) — voir §6 de `contracts/diagnostic/README.md`.

## 3.7 Conventions de nommage transverses

| Convention | Où elle s'applique |
|---|---|
| `snake_case` | `problem_id`, `service` (registre), noms de champs (`FieldSpec.name`) |
| `SCREAMING_SNAKE_CASE` | Codes métier (`resolution_code`, `escalation_reason`) |
| Préfixe `/diagnostic/` | Toutes les routes du contrat Diagnostic Engine, jamais mélangées aux routes métier classiques |
| `CMP-YYYYMMDD-XXXXXXXX` | Identifiants de ticket (`ComplaintService._generate_ticket_id`) |
| `X-User-ID`, `X-Internal-Secret`, `X-Request-ID` | En-têtes HTTP transverses (identité utilisateur, secret inter-service, corrélation de traces) |

## 3.8 Fichiers de premier niveau notables

- **`fastapi/services_registry.yaml`** : seule source déclarative de "quels
  microservices existent" pour le Diagnostic Engine (voir [2.4](02-architecture.md#24-le-pattern-capability-registry)).
- **`docker-compose.yml`** : définit cinq services (`rasa`, `actions`,
  `postgres`, `pgadmin`, `fastapi`) mais seuls `rasa` et `actions` sont
  utilisés en pratique dans ce projet — voir [10.2](10-deploiement.md#102-ce-qui-tourne-en-conteneur-vs-nativement-sur-lhôte).
- **`utils.txt`** : aide-mémoire des commandes réellement utilisées pour
  lancer chaque processus natif (moteur FastAPI, services) — référence de fait
  pour le chapitre [10. Déploiement](10-deploiement.md).

---

Suite : [4. Architecture des services](04-services.md)
