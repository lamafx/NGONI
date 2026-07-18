← [Sommaire](README.md) | [11. Maintenance](11-maintenance.md)

# 12. Journalisation et supervision

## 12.1 Logs FastAPI

Configurés en tête de `app/main.py` (`logging.basicConfig`, niveau `INFO`,
format `%(asctime)s %(levelname)-8s %(name)s: %(message)s`) — nécessaire
explicitement car `uvicorn` ne configure que ses propres loggers
(`uvicorn`, `uvicorn.access`, `uvicorn.error`), jamais le logger racine ; sans
cette configuration, tous les `logger.info(...)` applicatifs seraient
silencieusement avalés.

En développement, la sortie standard du processus natif est généralement
redirigée vers des fichiers (convention observée dans ce projet :
`fastapi/engine8000_stdout.log`, `engine8000_stderr.log`) — pas un choix
d'architecture figé, simplement la pratique courante pour garder une trace
entre deux sessions de développement.

## 12.2 Logs Rasa / Actions

En conteneur Docker, consultables via :

```powershell
docker compose logs -f rasa
docker compose logs -f actions
```

L'action server journalise notamment les décisions de classification
diagnostique (`_score_capabilities*`) et les échecs d'appel réseau vers le
moteur (`requests.RequestException`, avalés en repli fonctionnel — voir
[5.8](05-communication.md#58-gestion-des-pannes) — mais toujours dignes
d'investigation si répétés).

## 12.3 Traçabilité inter-services

### Corrélation par `trace_id` / `X-Request-ID`

Chaque appel du Diagnostic Engine vers un microservice porte un
`X-Request-ID` identique au `trace_id` généré côté moteur — permet de
retrouver la même requête dans les logs des deux côtés (moteur et
microservice). Format de log structuré utilisé côté pipeline/router
(préfixe `[DIAG][ENGINE]`) :

```
[DIAG][ENGINE] session=<id> trace_id=<uuid> stage=invoke target=<url> entities={...}
[DIAG][ENGINE] session=<id> trace_id=<uuid> stage=outcome result=RESOLVED resolution_code=WITHDRAWAL_UNDER_REVIEW
```

Les étapes journalisées (`stage=`) couvrent tout le cycle de vie d'une
résolution : `request_in`, `lookup`, `validate`, `invoke`, `outcome`,
`audit`. Le Capability Registry utilise le même préfixe pour son propre
cycle de vie : `[DIAG][REGISTRY]` (chargement de `services_registry.yaml`,
échecs de rafraîchissement).

### Audit persistant (`DiagnosticAuditRepository`)

Chaque appel à `POST /diagnostic/resolve` (y compris `NEED_MORE_INFO`, qui
n'appelle pourtant aucun microservice) est tracé en base dans une même
transaction :

- **`DiagnosticAuditLog`** : une ligne par appel — `trace_id`, `session_id`,
  `user_id`, `service`, `problem`, `called_endpoint`, `request_entities`,
  `outcome`, `outcome_detail`, `latency_ms`.
- **`DiagnosticSession`** : une ligne par conversation, mise à jour à chaque
  tour (`status` ∈ `IN_PROGRESS`/`RESOLVED`/`ESCALATED`, `turns_count`,
  `last_outcome`) — vue agrégée utile pour un futur tableau de bord de
  supervision.

Une panne d'écriture de l'audit (base indisponible, contrainte violée) **ne
fait jamais échouer la réponse déjà calculée pour l'utilisateur** — seule
une entrée de log d'avertissement est produite : la traçabilité est
secondaire par rapport au service rendu.

### Traçabilité étendue (`audit.agent_actions`)

Au-delà du Diagnostic Engine, deux autres décisions autonomes sont
désormais tracées via une table générique cross-domaine (voir
[15.6](15-modele-donnees.md#156-schéma-audit--traçabilité-cross-domaine)) :

- **Réponses FAQ servies** (`/faq/search` et le raccourci `/api/chat`) —
  question posée, question FAQ effectivement matchée (ou absence de
  correspondance), score de similarité.
- **Classification d'un problème diagnostique** côté serveur d'actions Rasa
  — jusqu'ici totalement invisible (aucun log, même éphémère, n'existait
  pour cette étape). Tracée uniquement au **verrouillage** d'un nouveau
  problème (pas à chaque tour d'une conversation déjà verrouillée), via un
  appel HTTP `POST /audit/actions` best-effort (`rasa/actions/diagnostic.py::_report_agent_action`) —
  ce process n'a pas d'accès direct à la base, contrairement au moteur
  FastAPI.

Deux liens résultants sont également persistés a posteriori (absents
jusqu'ici, voir [15.6](15-modele-donnees.md#156-schéma-audit--traçabilité-cross-domaine)) :
le ticket créé automatiquement par une escalade `SERVICE_UNAVAILABLE`
(`diagnostic_audit_log.related_ticket_id`), et le ticket créé depuis un
feedback suggestion/plainte (`feedback.entries.ticket_id`).

**Hors scope de cette extension** (voir [15.6](15-modele-donnees.md#156-schéma-audit--traçabilité-cross-domaine)) :
les décisions NLU pures (fallback déclenché, hors-sujet) restent non
tracées structurellement à ce stade — jugé trop risqué d'instrumenter cette
logique de dialogue finement calibrée sans une raison plus forte ; seul le
tracker Rasa brut (`events`) en garde une trace non structurée.

## 12.4 Gestion des erreurs

| Situation | Comportement |
|---|---|
| Microservice de diagnostic injoignable / disjoncteur ouvert | Escalade automatique (`SERVICE_UNAVAILABLE`) + ticket créé sans confirmation utilisateur (voir [5.8](05-communication.md#58-gestion-des-pannes)) |
| Rasa injoignable depuis le moteur (`/api/parse`, `/api/chat`) | 3 tentatives avec délai, puis `HTTPException(502)` |
| Service d'embeddings indisponible côté action server | Repli sur le score par mots-clés |
| Écriture d'audit en échec | Avertissement journalisé, réponse utilisateur non affectée |
| Corps de requête non conforme à un contrat (`extra: forbid` côté Pydantic) | `422 Unprocessable Entity`, jamais silencieusement ignoré |

## 12.5 Limites actuelles de supervision

Aucun système centralisé de logs ni de métriques n'est en place à ce stade
(pas d'agrégateur type ELK/Loki, pas de dashboard de suivi des diagnostics
résolus/escaladés bien que `DiagnosticSession` fournisse déjà la donnée
nécessaire à un tel dashboard). Voir
[13. Limitations actuelles](13-limitations.md) et
[14. Perspectives d'évolution §14.5](14-evolutions.md#145-observabilité-centralisée).

---

Suite : [13. Limitations actuelles](13-limitations.md)
