# ia-service — Workflows & Communications

## Rôle

Assistant conversationnel de premier niveau pour la plateforme Ngoni. Comprend le français (Rasa NLU), répond aux FAQ par similarité sémantique, diagnostique des problèmes réels en interrogeant les microservices propriétaires (`wallet-service`, `user-service`), crée des tickets d'escalade / réclamation, et collecte le feedback utilisateur.

Principe directeur : **le microservice métier décide** (`RESOLVED` / `ESCALATE` / `NEED_MORE_INFO`), **le moteur FastAPI transporte et normalise**, **Rasa affiche**. Aucun seuil métier ne vit dans le bot ni dans le moteur.

---

## Architecture globale

```
Utilisateur (web / mobile)
  │  texte libre
  ▼
Rasa NLU + Core (:5005)          ← Docker
  │  webhook action
  ▼
Action Server rasa/actions (:5055) ← Docker
  │  HTTP JSON
  ▼
Moteur FastAPI NGONI Engine (:8000) ← natif
  ├── FAQ (embeddings e5-base + pgvector)
  ├── Diagnostic Engine + Capability Registry
  ├── Complaints / tickets
  ├── Feedback / ratings
  └── Embeddings (singleton partagé)
        │
        ├── GET/POST /diagnostic/* → wallet-service (ou wallet_stub :3103)
        ├── GET/POST /diagnostic/* → user-service   (ou user_stub :3104)
        └── SQL → PostgreSQL (:5432)
              └── tracker store Rasa (table events)
```

Aucune communication Kafka dans ce périmètre : tous les échanges sont **HTTP/JSON synchrones**, avec timeouts et circuit breaker côté Diagnostic Engine.

---

## Flux 1 : FAQ sémantique

```
Utilisateur
  └─ "comment fonctionne le parrainage ?" / "mon compte es bloké"
       → Rasa NLU : intent=ask_faq (DIETClassifier + char_wb n-grams)
       → ActionFaqSearch
            → POST /faq/search { question }
                 → embed_query() + cosinus vs embeddings FAQ précalculés
                 → seuil DEFAULT_THRESHOLD=0.85
            ← answer + flow.status = matched | not_found
       → réponse + boutons 👍 / 👎 (notation)
```

Navigation FAQ (browse) :

```
Utilisateur
  └─ "montre-moi les FAQ" / sélection catégorie
       → intents browse_faq / select_faq_category / select_faq_question
       → ActionBrowseFaq → GET /faq/suggestions
```

---

## Flux 2 : Diagnostic métier (Capability Registry)

### 2.1 — Découverte des capacités (périodique)

```
Moteur FastAPI (startup + poll toutes les REGISTRY_POLL_INTERVAL_SECONDS, défaut 300s)
  → pour chaque entrée de services_registry.yaml :
       GET {base_url}/diagnostic/manifest
         Headers: X-Internal-Secret, X-Request-ID
  → embed_passage_batch(description + example_phrases)
  → registre en mémoire (service, problem_id, champs requis, embeddings)

Rasa Action Server
  → GET /diagnostic/capabilities (cache 5 min côté actions)
       ← catalogue agrégé, seule source consultée par le bot
```

Ajouter un problème diagnosticable dans un microservice = **aucun** redéploiement du moteur ni de Rasa : il apparaît au prochain cycle de rafraîchissement.

### 2.2 — Classification du problème (côté Action Server)

```
Utilisateur
  └─ "mon retrait est bloqué depuis hier"
       → Rasa NLU : intent=diagnostic
       → ActionRunDiagnosticStep
            1. GET /diagnostic/capabilities (cache)
            2. POST /embeddings/query { text }
            3. Score cosinus vs catalogue
               (+ repli segmentation en clauses, filtre négation/résolution,
                  tiebreak mots-clés, seuils MIN_EMBEDDING_SIMILARITY=0.84)
            4. Demande de confirmation à l'utilisateur
       ← "Je crois comprendre qu'il s'agit d'un retrait bloqué… Oui / Non ?"
```

### 2.3 — Résolution (côté Diagnostic Engine)

```
Utilisateur confirme "oui"
  → ActionDecideEscalation
       → POST /diagnostic/resolve
            Headers: X-User-ID
            Body: { session_id, service, problem, entities }
                 │
                 ▼
            DiagnosticPipeline.resolve()
              1. lookup (service, problem) dans le Registry
              2. validation des champs requis → NEED_MORE_INFO si manquants
              3. POST {base_url}/diagnostic/{problem_id}
                   Headers: X-Internal-Secret, X-Request-ID
                   → wallet / user (réel ou stub)
              4. audit_repository.record(trace_id, latence, outcome)
                 │
                 ├── RESOLVED  → message formaté à l'utilisateur
                 ├── ESCALATE  → création ticket (sans confirmation supplémentaire
                 │               si SERVICE_UNAVAILABLE)
                 └── NEED_MORE_INFO → collecte des missing_fields via formulaire Rasa
```

### 2.4 — Résilience

| Panne | Comportement |
|-------|--------------|
| Microservice injoignable / circuit ouvert | `ESCALATE` + `escalation_reason=SERVICE_UNAVAILABLE` + ticket `created_by=ai_auto_escalation` (jamais d'erreur HTTP silencieuse) |
| Embeddings indisponibles | Repli score mots-clés côté action server |
| Registry vide / périmé | Dernier cache actions (≤ 5 min) |

---

## Flux 3 : Réclamation manuelle

```
Utilisateur
  └─ "je veux signaler un problème" / intent create_reclamation | plainte
       → Formulaire Rasa (catégorie, description, urgence…)
       → ActionCreateTicket
            → POST /tickets/create (alias /complaints/create)
                 { category, description, urgency, user_id,
                   created_by: user_reclamation_form }
            ← { ticket_id: "CMP-YYYYMMDD-XXXXXXXX", status: "open" }
       → ticket communiqué à l'utilisateur
```

---

## Flux 4 : Feedback et notation

```
Utilisateur clique "pas utile" après une réponse FAQ
  → intent rate_response_not_useful
  → ActionRecordResponseRating
       → POST /feedback/ratings
            { interaction_type, question, answer, is_useful, user_id }

Utilisateur envoie une suggestion / plainte libre
  → ActionStoreSuggestion / ActionAcknowledgeComplaint
       → POST /feedback
            → peut créer un ticket associé (created_by=ai_feedback_ticket)
```

---

## Flux 5 : Garde-fou vocabulaire (hors-sujet / insultes)

```
Utilisateur
  └─ message hors-vocabulaire / inapproprié
       → DIETClassifier (peut être sur-confiant en softmax)
       → VocabularyCoverageGuard (composant NLU custom)
            si aucun mot ≥ 3 lettres reconnu dans le vocabulaire d'entraînement
            → force confiance intention à 0.0
       → FallbackClassifier → nlu_fallback / inappropriate_language
       → recadrage, pas de faux intent métier (FAQ / diagnostic)
```

---

## Flux 6 : Interface de test intégrée (dev uniquement)

```
Navigateur → GET /chat (widget HTML)
  → POST /api/chat { text, user_id }
       ├── si /model/parse → intent exact ask_faq
       │     → court-circuit FaqService.find_best_answer (sans webhook Rasa)
       └── sinon
             → POST Rasa /webhooks/rest/webhook
```

⚠️ Aucune auth utilisateur sur le périmètre assistant en développement (voir `13-limitations.md`). Seuls `X-Internal-Secret` (diagnostic inter-services) et l'admin core-service sont protégés.

---

## Appels inter-services HTTP

### Appels sortants (depuis ia-service / moteur)

| Appelant | Appelé | Endpoint | But |
|----------|--------|----------|-----|
| Action Server | Moteur FastAPI | `POST /faq/search`, `GET /faq/suggestions` | FAQ |
| Action Server | Moteur FastAPI | `GET /diagnostic/capabilities`, `POST /diagnostic/resolve` | Diagnostic |
| Action Server | Moteur FastAPI | `POST /embeddings/query[/batch]` | Similarité sémantique |
| Action Server | Moteur FastAPI | `POST /tickets/create`, `POST /feedback*` | Tickets / feedback |
| Moteur FastAPI | wallet-service | `GET /diagnostic/manifest`, `POST /diagnostic/{problem_id}` | Diagnostic wallet |
| Moteur FastAPI | user-service | `GET /diagnostic/manifest`, `POST /diagnostic/{problem_id}` | Diagnostic user |
| Moteur FastAPI | Rasa | `/model/parse`, `/webhooks/rest/webhook` | Proxy interface de test |

### Appels entrants vers ia-service

| Appelant | Endpoint | But |
|----------|----------|-----|
| Client mobile / web (canal rest) | `POST Rasa /webhooks/rest/webhook` | Conversation |
| Microservices (contrat) | — | Les services métier **exposent** le contrat ; ils n'appellent pas ia-service |

### Stubs de développement (remplacent wallet/user)

| Stub | Port | Problèmes exposés (exemples) |
|------|------|------------------------------|
| `wallet_stub` | `3103` | `withdrawal_pending`, `topup_not_credited`, `gift_not_received` |
| `user_stub` | `3104` | `kyc_status_issue`, `account_access_blocked`, `compliance_hold_blocking`, `account_deletion_status`, `parental_consent_status` |

Basculer stub → service réel = changer `WALLET_SERVICE_BASE_URL` / `USER_SERVICE_BASE_URL` (et secrets) dans la config, dès que le service Laravel implémente le contrat `contracts/diagnostic/v1/`.

---

## Topics Kafka

_Aucun topic Kafka publié ni consommé par ia-service dans le périmètre actuel._

La communication avec le reste de la plateforme passe uniquement par le **contrat HTTP de diagnostic** et, côté FAQ produit, par le module FAQ de `ngoni-core-service` (écrans app, hors chatbot — voir `06-api-reference.md` §6.11).

---

## Modèle de données principal (PostgreSQL)

| Schéma | Contenu |
|--------|---------|
| `core` | `faq_items` (+ embeddings `vector(768)` / pgvector) |
| `complaints` | tickets `CMP-…` |
| `feedback` | suggestions / plaintes, `response_ratings` |
| `diagnostic` | sessions + `diagnostic_audit_log` |
| `wallet` / `users` | clones lecture seule pour les stubs de dev |
| *(défaut)* | `events` — tracker store Rasa |

Détail : [15-modele-donnees.md](15-modele-donnees.md).

---

## Ports de référence

| Composant | Port |
|-----------|------|
| Rasa | 5005 |
| Action Server | 5055 |
| Moteur FastAPI | 8000 |
| wallet_stub / wallet-service (diagnostic) | 3103 |
| user_stub (diagnostic, local) | 3104 |
| PostgreSQL | 5432 |
| pgAdmin (dev) | 5050 |
