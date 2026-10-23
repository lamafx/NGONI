← [Sommaire](README.md) | [5. Communication entre les services](05-communication.md)

# 6. Référence API

> **⚠️ Sécurité — environnement de développement uniquement.** Aucun des
> endpoints listés ci-dessous (FastAPI, Rasa, services wallet/user) n'est
> protégé par une authentification utilisateur, à l'exception du module
> admin de `ngoni-core-service` (§6.11, `assertInternalAuth`) et du header
> interne `X-Internal-Secret` entre le moteur et les microservices de
> diagnostic. Voir [13. Limitations actuelles](13-limitations.md).

## 6.0 Conventions communes

- **Format des erreurs FastAPI** : `{"detail": "message"}`, codes HTTP
  standards (`400` entrée invalide, `404` ressource introuvable, `502`
  dépendance amont injoignable).
- **En-têtes transverses** : `X-User-ID` (identité utilisateur, requise sur
  `/diagnostic/resolve`), `X-Internal-Secret` (secret partagé entre le
  moteur et un microservice de diagnostic), `X-Request-ID` (corrélation de
  traces, = `trace_id`).
- **Encodage** : JSON UTF-8 partout, `Content-Type: application/json`.
- Les exemples ci-dessous sont donnés au format `curl`/PowerShell,
  directement rejouables contre une instance locale (voir
  [10. Déploiement](10-deploiement.md)).

## 6.1 FastAPI — FAQ (`/faq`, base `http://localhost:8000`)

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/faq/` | Liste toutes les FAQ (`FaqItemResponse[]`). |
| `POST` | `/faq/` | File d'attente d'ajout en masse. Corps : `FaqCreate[]` → `202 Accepted`, `{ "queued": n }`. |
| `GET` | `/faq/random?count=2` | `count` (1-10, défaut 2) questions aléatoires, texte seul. |
| `GET` | `/faq/suggestions?count=10` | `count` (1-10, défaut 10) questions aléatoires groupées par catégorie, réponse incluse. |
| `POST` | `/faq/search` | Recherche sémantique — détaillé ci-dessous. |

`FaqCategory` : `ACCOUNT`, `WALLET`, `COINS`, `VPP`, `LPP`, `WITHDRAWAL`,
`NGONI_PLUS`, `KYC`, `PARENTAL_CONTROL`, `GIFTS`, `ASSISTANCE`, `GENERAL`.
`FaqStatus` : `DRAFT`, `PUBLISHED`, `ARCHIVED`.

#### `POST /faq/search`

- **Objectif** : trouver la FAQ la plus proche sémantiquement d'une question
  libre, y compris avec fautes de frappe ou reformulation.
- **Corps** : `{ "question": string }`
- **Réponse `200`** : `FaqSearchResponse`
- **Codes d'erreur** : `422` si `question` absent.

```json
// Requête
POST /faq/search
{ "question": "mon compte es bloké" }

// Réponse 200
{
  "answer": "Un compte peut être temporairement bloqué en cas de contrôle de sécurité...",
  "flow": {
    "route": "Rasa -> FastAPI",
    "status": "matched",
    "note": "",
    "matched_question": "Pourquoi mon compte est-il bloqué ?"
  }
}
```

Si aucune correspondance ne dépasse le seuil de similarité configuré
(`DEFAULT_THRESHOLD`, voir [9. Configuration](09-configuration.md)),
`flow.status` vaut `not_found` et `answer` est `null`.

## 6.2 FastAPI — Diagnostic (`/diagnostic`)

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/diagnostic/capabilities` | Agrège tous les manifestes connus — seule source consultée par Rasa. |
| `POST` | `/diagnostic/resolve` | Point d'entrée du Diagnostic Engine — détaillé ci-dessous. |
| `POST` | `/diagnostic/escalate` | Relais générique vers la création de ticket à partir d'un `EscalateOutcome` déjà construit. |
| `POST` | `/diagnostic/debug/classify` | Outil de debug : score de similarité d'un texte contre tout le catalogue. |
| `POST` | `/diagnostic/search` | Route héritée (`ILIKE` sur `diagnostic_records`), non liée au Diagnostic Engine par manifeste. |

#### `GET /diagnostic/capabilities`

- **Objectif** : lister tous les couples (service, problème) actuellement
  diagnosticables, avec leurs champs requis et leurs embeddings précalculés.
- **Paramètres** : aucun.
- **Réponse `200`** : `CapabilitiesResponse`

```json
{
  "problems": [
    {
      "service": "wallet",
      "id": "withdrawal_pending",
      "label": "Retrait bloqué ou en attente",
      "description": "L'utilisateur a demandé un retrait qui reste bloqué ou en attente depuis un certain temps.",
      "keywords": ["retrait", "bloqué", "en attente"],
      "required_fields": [
        { "name": "transaction_reference", "type": "string", "pattern": "^WDR-[A-Z0-9]+$" }
      ],
      "optional_fields": [],
      "embedding": [0.0123, -0.0456, "... 768 valeurs"],
      "example_embeddings": ["... un vecteur par example_phrase"]
    }
  ]
}
```

#### `POST /diagnostic/resolve`

- **Objectif** : point d'entrée unique du Diagnostic Engine — résout ou
  escalade un problème signalé par l'utilisateur, en interrogeant en direct
  le microservice propriétaire du problème.
- **En-tête requis** : `X-User-ID` (identité utilisateur, jamais dans le corps).
- **Corps** : `DiagnosticResolveRequest`

  | Champ | Type | Obligatoire | Description |
  |---|---|---|---|
  | `session_id` | string | oui | Identifiant de la conversation Rasa |
  | `service` | string (`snake_case`) | oui | Nom du service ciblé (ex. `wallet`) |
  | `problem` | string (`snake_case`) | oui | `problem_id` déclaré par le manifeste du service |
  | `entities` | object | non | Champs collectés auprès de l'utilisateur |

- **Réponse `200`** : une des trois formes discriminées par `outcome`
  (voir [7.3 du contrat](../contracts/diagnostic/README.md) pour la
  sémantique complète) :

```json
// RESOLVED
{
  "outcome": "RESOLVED",
  "message": "Votre retrait WDR-HJCOZRCVCOAY est en cours d'examen manuel, sous 24h ouvrées.",
  "resolution_code": "WITHDRAWAL_UNDER_REVIEW",
  "data": { "estimated_hours": 24 }
}

// ESCALATE
{
  "outcome": "ESCALATE",
  "message": "Je transmets votre demande à notre équipe support.",
  "escalation_reason": "HOLD_REQUIRES_MANUAL_REVIEW",
  "escalation_payload": {
    "category": "Wallet",
    "urgency": "high",
    "context": { "service": "wallet", "problem": "withdrawal_pending" }
  }
}

// NEED_MORE_INFO
{
  "outcome": "NEED_MORE_INFO",
  "missing_fields": ["transaction_reference"]
}
```

- **Codes d'erreur** :
  | Code | Cas |
  |---|---|
  | `404` | Couple `(service, problem)` inconnu du Capability Registry (`UnknownProblem`) — le manifeste ne le déclare pas. |
  | `422` | Corps non conforme à `DiagnosticResolveRequest` (ex. `service`/`problem` pas en `snake_case`). |

  Le cas "microservice cible injoignable" **n'est jamais une erreur HTTP** :
  il produit une réponse `200` avec `outcome: "ESCALATE"` et
  `escalation_reason: "SERVICE_UNAVAILABLE"` (voir [5.8](05-communication.md#58-gestion-des-pannes)).

## 6.3 FastAPI — Réclamations (`/complaints`)

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/complaints/{ticket_id}` | Détail d'un ticket (`ComplaintResponse`), `404` si introuvable. |
| `POST` | `/complaints/create` (alias `/tickets/create`) | Crée un ticket. |

#### `POST /complaints/create`

- **Corps** : `TicketCreateRequest`

  | Champ | Type | Obligatoire | Description |
  |---|---|---|---|
  | `category` | string | oui | Catégorie libre du ticket |
  | `description` | string | oui | Description du problème |
  | `urgency` | string | non (défaut `medium`) | `low` \| `medium` \| `high` |
  | `summary` | string | non | Résumé généré par le bot avant confirmation |
  | `context` | object | non | Contexte libre (jamais interprété, uniquement tracé) |
  | `user_id` | string | non | Identité utilisateur |
  | `created_by` | string | non (défaut `user_reclamation_form`) | `user_reclamation_form` \| `user_diagnostic_escalation` \| `ai_auto_escalation` \| `ai_feedback_ticket` |

- **Réponse `200`** : `TicketCreateResponse` — `{ "ticket_id": "CMP-20260717-3F9A2B1C", "status": "open", "message": "..." }`

### Gestion admin des tickets — `/admin/complaints`

> **Protégé.** Tout le routeur exige le header `X-Internal-Secret` (valeur
> `ADMIN_INTERNAL_SECRET`, voir [9. Configuration](09-configuration.md)) —
> première route de ce périmètre à ne **pas** suivre la politique
> "aucune authentification" décrite en tête de ce chapitre (voir
> [13.1](13-limitations.md#131-absence-dauthentification-et-dautorisation)).
> `401` si le secret est absent/incorrect ou non configuré côté serveur.

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/admin/complaints/?status=&category=&urgency=&created_by=&limit=&offset=` | Liste paginée (`limit` 1-200, défaut 50), filtres optionnels, triée par date de création décroissante. |
| `GET` | `/admin/complaints/{ticket_id}` | Détail d'un ticket, `404` si introuvable. |
| `PATCH` | `/admin/complaints/{ticket_id}` | Change le statut. Corps `{ "status": string }`. |

- **Cycle de statuts** : `OPEN` (défaut à la création) → `IN_PROGRESS` →
  `RESOLVED` / `CLOSED` — pas de machine à états stricte (`OPEN` → `CLOSED`
  directement reste autorisé). `400` si `status` n'appartient pas à cet
  ensemble.
- **En-tête `X-User-ID`** (optionnel) : identité de l'admin appelant,
  persistée dans `updated_by` à chaque `PATCH` — traçabilité humaine,
  distincte de `audit.agent_actions` (réservé aux décisions autonomes de
  l'IA, voir [6.7](#67-fastapi--traçabilité-des-actions-autonomes-audit)).

```json
// PATCH /admin/complaints/CMP-20260717-820E0A92
// Header: X-Internal-Secret: <secret>, X-User-ID: admin-1
{ "status": "IN_PROGRESS" }

// Réponse 200
{ "ticket_id": "CMP-20260717-820E0A92", "status": "IN_PROGRESS", "updated_by": "admin-1", "...": "..." }
```

## 6.4 FastAPI — Feedback (`/feedback`)

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/feedback` | Corps `FeedbackCreateRequest` (`type`, `message`, `user_id`). Peut créer un ticket associé (`ticket_id` dans la réponse) selon `type`. |
| `GET` | `/feedback?type=...` | Liste les entrées d'un type donné. |
| `POST` | `/feedback/ratings` | Notation d'une réponse FAQ (`interaction_type`, `question`, `answer`, `is_useful`, `user_id`). |
| `GET` | `/feedback/ratings?interaction_type=&is_useful=` | Liste les notations, filtres optionnels. |

## 6.4bis FastAPI — Conversations et prise en charge humaine

Ajouté le 2026-09-16. Raisonnement complet (cycle de vie, mise en silence du
bot, qui écrit l'historique) : [19. Prise en charge humaine](19-prise-en-charge-humaine.md).

### Côté usager

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/conversations/escalate` | `{ conversation_id, user_id?, reason? }` → place la conversation dans la file des conseillers. N'interrompt PAS l'assistant : tant que personne n'a repris la main, il continue de répondre. |
| `POST` | `/conversations/turns` | Journalise un tour (`user_text`, `intent?`, `confidence?`, `bot_messages[]`) pour les clients qui interrogent Rasa directement. Réponse : `handoff` — `true` signifie « cesse d'interroger Rasa, un humain répond ». Inutile pour les clients qui passent par `POST /api/chat`, déjà journalisés côté serveur. |
| `POST` | `/conversations/withdraw` | `{ conversation_id, reason? }` — retire une demande de conseiller encore EN ATTENTE. Réponse `withdrawn: false` (et non une erreur) quand un conseiller a déjà pris le dossier : on ne l'efface pas de sa file dans son dos. Idempotent sur une conversation qui n'était pas escaladée. Appelée par `action_cancel_human_agent_request` (intention `cancel_human_agent_request`). |
| `GET` | `/conversations/{id}/updates?after=` | Messages écrits depuis `after` (bot et conseiller ; jamais ceux de l'usager, déjà affichés chez lui) + état de la prise en charge. |

### Côté conseiller / administration — `X-Internal-Secret` obligatoire

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/admin/conversations/?status=&assigned_to=&escalated=&unassigned=` | La file, sans les messages (liste légère). |
| `GET` | `/admin/conversations/{id}` | Le fil complet. |
| `GET` | `/admin/conversations/{id}/context` | Résumé de reprise : intentions vues, diagnostic tenté, tickets liés, chronologie — reconstitué depuis les traces réelles. |
| `POST` | `/admin/conversations/{id}/assign` | `{ agent_id }` — prise en charge. `409` si un autre conseiller la tient (`?force=true` pour reprendre). Le bot se tait à partir de là. |
| `POST` | `/admin/conversations/{id}/messages` | `{ text, agent_id? }` — réponse humaine. `409` tant que la conversation n'est pas prise en charge. |
| `POST` | `/admin/conversations/{id}/resolve` | `{ agent_id?, note? }` — clôture ; le bot reprend la main au prochain message de l'usager. |
| `POST` | `/admin/complaints/{ticket_id}/assign` | `{ agent_id }` — prise en charge d'une réclamation (attribue et passe en `IN_PROGRESS`, sauf ticket déjà résolu/clos). |
| `GET`/`POST` | `/admin/agents/` | Annuaire des conseillers. Le statut renvoyé est dérivé de l'activité (15 min sans action = hors ligne), `declared_status` conserve le statut déclaré. |
| `PATCH` | `/admin/agents/{id}/status` | `{ status }` parmi `online` / `away` / `offline`. |
| `GET` | `/admin/dashboard/summary?days=` | KPI + variation par rapport à la période précédente de même durée. |
| `GET` | `/admin/dashboard/conversation-volume?days=` | Série journalière (conversations et messages). |
| `GET` | `/admin/dashboard/intent-distribution?days=` | Répartition réelle des intentions classées par le moteur ; payloads structurés comptés à part (`unclassified`). |
| `GET` | `/admin/dashboard/recent-activity?limit=` | Flux d'événements (tickets, escalades, prises en charge, actions autonomes). |
| `GET` | `/admin/diagnostics/runs?days=` | Diagnostics exécutés, latence moyenne, répartition par issue. |
| `GET` | `/admin/system/health` | Sonde réelle : PostgreSQL, Rasa, et chaque service de `services_registry.yaml`. Statut global = le pire des statuts individuels. |
| `GET` | `/admin/users/?limit=&offset=` | Usagers vus par le support : identifiant de contact, volumes, tickets, dernière activité. Agrégation pure — aucune table d'utilisateurs n'existe dans `ia`, et aucun nom/email n'est inventé (les profils appartiennent à `ngoni-user-service`). |
| `GET` | `/admin/users/{user_id}` | Historique : conversations et tickets de cet usager. |

## 6.5 FastAPI — Embeddings (`/embeddings`)

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/embeddings/query` | `{ "text": string }` → `{ "embedding": float[768] }`. |
| `POST` | `/embeddings/query/batch` | `{ "texts": string[] }` → `{ "embeddings": float[][] }` — un seul passage modèle pour tout le lot. |

## 6.6 FastAPI — Interface de test et proxy Rasa

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/` | Page d'accueil minimale. |
| `GET` | `/chat` | Widget de chat HTML/JS autonome, pour tester le bot sans frontend dédié. |
| `POST` | `/api/parse` | Proxy vers Rasa `/model/parse`. |
| `POST` | `/api/chat` | `{ "text": string, "user_id": string }` → `{ "messages": [...] }`. Court-circuite vers la FAQ sémantique si l'intention est exactement `ask_faq`, sinon relaie vers le webhook Rasa. |

## 6.7 FastAPI — Traçabilité des actions autonomes (`/audit`)

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/audit/actions` | Ingestion générique d'une décision autonome (voir [15. Modèle de données](15-modele-donnees.md#156-schéma-audit--traçabilité-cross-domaine)). Corps `AgentActionCreateRequest` (`domain`, `action_type`, `session_id`, `input_data`, `output_data`...). Appelée notamment par le serveur d'actions Rasa pour tracer ses propres décisions de classification diagnostic — appel best-effort côté appelant, ne bloque jamais une réponse utilisateur. |
| `GET` | `/audit/actions?domain=&session_id=` | Liste les actions tracées, filtres optionnels — usage debug/audit, pas encore de tableau de bord dédié (voir [14.5](14-evolutions.md#145-observabilité-centralisée)). |

## 6.8 Rasa — conversation (`http://localhost:5005`)

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/webhooks/rest/webhook` | Point d'entrée conversationnel principal. |
| `POST` | `/model/parse` | Classification NLU seule, sans avancer la conversation. |
| `GET` | `/status` | Modèle actuellement chargé. |

#### `POST /webhooks/rest/webhook`

- **Objectif** : envoyer un message utilisateur au bot et recevoir sa
  réponse (texte + éventuels boutons).
- **Corps** : `{ "sender": string, "message": string }`. `message` peut être
  du texte libre, ou un payload structuré `/intent{"entité":"valeur"}` pour
  simuler un clic de bouton (ex. `/select_faq_category{"faq_category":"WALLET"}`).
- **Réponse `200`** : tableau de messages bot.

```json
// Requête
{ "sender": "demo-9f2c", "message": "mon retrait est bloqué depuis hier" }

// Réponse 200
[
  { "text": "Je crois comprendre qu'il s'agit d'un retrait bloqué ou en attente. C'est bien ça ?",
    "buttons": [{ "title": "Oui", "payload": "/affirm" }, { "title": "Non", "payload": "/deny" }] }
]
```

**Serveur d'actions** (`http://localhost:5055`) : `POST /webhook`, appelé
uniquement par Rasa Core lui-même — jamais par un client final.

## 6.9 Contrat Diagnostic Engine ↔ microservices

Décrit intégralement par [`contracts/diagnostic/README.md`](../contracts/diagnostic/README.md)
et les schémas JSON de `contracts/diagnostic/v1/` — non dupliqué ici pour
éviter toute divergence entre deux sources. Résumé des routes exigées d'un
microservice diagnosticable :

| Route | Méthode | Contrat |
|---|---|---|
| `/diagnostic/manifest` | `GET` | `capability-manifest.schema.json` |
| `/diagnostic/{problem_id}` | `POST` | `service-invocation-request.schema.json` → `service-invocation-response.schema.json` |

## 6.10 Services wallet/user (backend de développement du Diagnostic Engine)

**Wallet service** — `http://127.0.0.1:3103/api/v1` :

| Méthode | Route | Problème résolu |
|---|---|---|
| `GET` | `/diagnostic/manifest` | Auto-description (3 problèmes) |
| `POST` | `/diagnostic/withdrawal` | `withdrawal_pending` |
| `POST` | `/diagnostic/topup` | `topup_not_credited` |
| `POST` | `/diagnostic/gift` | `gift_not_received` |

**User service** — `http://127.0.0.1:3104/api/v1` :

| Méthode | Route | Problème résolu |
|---|---|---|
| `GET` | `/diagnostic/manifest` | Auto-description (5 problèmes) |
| `POST` | `/diagnostic/kyc_status` | `kyc_status_issue` |
| `POST` | `/diagnostic/account_status` | `account_access_blocked` |
| `POST` | `/diagnostic/compliance_hold` | `compliance_hold_blocking` |
| `POST` | `/diagnostic/account_deletion` | `account_deletion_status` |
| `POST` | `/diagnostic/parental_consent` | `parental_consent_status` |

## 6.11 `ngoni-core-service` — module FAQ (hors périmètre principal)

Base URL : `http://localhost:3116/api/v1`. Documenté ici uniquement parce
qu'il porte le même contenu FAQ que le domaine `faq` du moteur FastAPI, côté
écrans web/mobile de l'application (pas le chatbot).

| Surface | Préfixe | Authentification |
|---|---|---|
| Public (web) | `/api/v1/public` | Aucune |
| Mobile | `/api/v1/mobile` | Aucune |
| Admin | `/api/v1/admin` | `assertInternalAuth` (interne) |

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/public/faq?category=&featured=&locale=` | Liste les FAQ publiées. |
| `GET` | `/public/faq/:slug?locale=` | Détail par slug. |
| `GET` | `/mobile/faq?category=&featured=&locale=` | Idem, canal mobile. |
| `GET` | `/mobile/faq/:id` | Détail par id. |
| `POST` | `/mobile/faq/match` | Correspondance par mots-clés (pas d'embeddings) + détection d'intention de plainte. |
| `GET` | `/admin/faq?status=&category=&locale=&search=&limit=&offset=` | Liste paginée, tous statuts. |
| `GET` | `/admin/faq/categories` | Catégories valides. |
| `POST` | `/admin/faq` | Création. |
| `PATCH` | `/admin/faq/:id` | Mise à jour partielle. |
| `DELETE` | `/admin/faq/:id` | Archive (pas une suppression physique). |

---

Suite : [7. Intégration des modèles IA](07-integration-ia.md)
