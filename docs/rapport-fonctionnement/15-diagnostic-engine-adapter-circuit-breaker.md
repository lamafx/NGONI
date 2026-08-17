← [14. Diagnostic Engine — pipeline et contrats](14-diagnostic-engine-pipeline-contracts.md) | → [16. Les domaines simples derrière l'admin](16-domaines-admin-complaints-feedback-audit.md)

# 15. Diagnostic Engine — adapter et disjoncteur

> **Rôle de ce document** : `app/domains/diagnostic/adapter.py`
> (`HttpDiagnosticAdapter`) et `circuit_breaker.py` — l'appel HTTP réel vers
> un microservice, et ce qui le protège d'une panne prolongée. Ce que fait
> l'appelant (le pipeline) avec le résultat est au
> [chapitre 14](14-diagnostic-engine-pipeline-contracts.md).

## Un seul Adapter aujourd'hui, extensible demain

Un seul protocole est supporté (`REST`, le seul déclaré par les manifestes
actuels). Une évolution future pourra sélectionner l'Adapter par un Factory
keyé sur le champ `protocol` du manifeste, sans modifier ni le Registry ni
le Pipeline.

## Le disjoncteur est **partagé**, pas recréé à chaque appel

`router.py::get_adapter()` (avec `@lru_cache`) construit **un seul**
`HttpDiagnosticAdapter` pour tout le process — le disjoncteur qu'il porte
doit accumuler ses échecs consécutifs **à travers** les requêtes. Un
Adapter recréé à chaque appel aurait un disjoncteur qui ne s'ouvre jamais,
chaque requête repartant avec un compteur à zéro.

## Paramètres

- Timeout par appel : **10 secondes** (`DIAGNOSTIC_CALL_TIMEOUT_SECONDS`).
- Seuil d'ouverture : **3 échecs consécutifs** (`CIRCUIT_BREAKER_FAILURE_THRESHOLD`)
  — délibérément bas : mieux vaut escalader vite un service réellement en
  panne que faire attendre plusieurs utilisateurs le même timeout complet
  chacun.
- Durée d'ouverture : **30 secondes** (`CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS`).
- Une clé de disjoncteur **par microservice** (`base_url`) — la panne d'un
  service n'affecte jamais l'état des autres.

## Deux natures d'échec, distinguées explicitement

1. **Panne réseau/HTTP** (`httpx.HTTPError`) → compte comme un échec du
   disjoncteur (`record_failure`).
2. **Réponse HTTP 200 mais non conforme** au contrat
   (`service-invocation-response.schema.json`, voir
   [chapitre 14](14-diagnostic-engine-pipeline-contracts.md)) → **ne
   compte PAS** comme un échec du disjoncteur. Une réponse 200 mal formée
   signale que le service répond, juste incorrectement — pas une panne
   réseau. Ouvrir le circuit sur un bug de contrat empêcherait aussi les
   **autres** problèmes (potentiellement corrects) de ce même service
   d'être appelés, pour une cause qui leur est étrangère.

Dans les deux cas, le résultat remonté au pipeline est un
`DiagnosticInvocationError` (ou sa sous-classe `CircuitBreakerOpenError`
si le disjoncteur était déjà ouvert et qu'**aucun appel réseau n'a été
tenté**) — distinction utile dans les logs/l'audit pour comprendre une
salve d'escalades sans y voir une salve de pannes réseau indépendantes.

## États du disjoncteur (`circuit_breaker.py`)

Implicites, déduits d'un état plutôt qu'une énumération à synchroniser :

- **FERMÉ** : les appels passent normalement.
- **OUVERT** : échec immédiat, aucun appel réseau tenté, pendant
  `reset_timeout_seconds`.
- **SEMI-OUVERT** : passé ce délai, un seul appel est laissé passer pour
  tester si le service est revenu ; son résultat referme ou rouvre le
  disjoncteur.

Verrou volontairement grossier (pas un verrou par clé) : la section
critique est de l'ordre de la microseconde, pas la peine de complexifier
pour un gain de concurrence invisible en pratique sur ce volume d'appels.

Volontairement indépendant de `httpx`/`asyncio` — aucune dépendance
externe, testable en isolation.
