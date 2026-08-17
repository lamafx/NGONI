← [13. Diagnostic Engine — le registre](13-diagnostic-engine-registry.md) | → [15. Diagnostic Engine — adapter et disjoncteur](15-diagnostic-engine-adapter-circuit-breaker.md)

# 14. Diagnostic Engine — pipeline et contrats

> **Rôle de ce document** : `app/domains/diagnostic/pipeline.py`
> (`DiagnosticPipeline.resolve`) et les contrats Pydantic
> (`contracts.py`) — la logique de résolution **générique**, sans aucune
> règle métier propre à un problème particulier.

## Un pipeline sans logique métier

Le fichier `pipeline.py` documente explicitement cette contrainte : toutes
les étapes ci-dessous sont **strictement identiques** quel que soit le
service ou le problème traité. La seule réaction "intelligente" du
pipeline — escalader automatiquement si le microservice cible est
injoignable — n'est pas une règle métier, c'est une politique de
résilience générique appliquée de la même façon à n'importe quel service.

## Les 3 étapes de `resolve()`

1. **Lookup** — remplace un `switch(service, problem)` par une lecture de
   dictionnaire dans l'index construit au [chapitre 13](13-diagnostic-engine-registry.md).
   Un couple inconnu lève `UnknownProblem` → `HTTP 404` côté
   `POST /diagnostic/resolve`.
2. **Validation générique de complétude** : l'ensemble des noms de champs
   requis (`required_fields`) est comparé à l'ensemble fourni. Un groupe de
   repli complet (`fallback_fields`) satisfait aussi la validation — ex.
   pas de référence de transaction mais date + montant du retrait — mais
   seulement s'il est **entièrement** collecté, jamais un mélange partiel
   des deux groupes (le Dialogue Manager ne bascule sur le repli qu'une
   fois celui-ci complet). Des champs manquants renvoient
   `NeedMoreInfoOutcome(missing_fields=[...])`, sans jamais appeler le
   microservice.
3. **Invocation + normalisation** — délègue à l'Adapter (voir
   [chapitre 15](15-diagnostic-engine-adapter-circuit-breaker.md)). Un
   microservice injoignable devient automatiquement
   `EscalateOutcome(escalation_reason="SERVICE_UNAVAILABLE")` — jamais une
   erreur brute renvoyée au chatbot.

## Traçabilité (Phase 6)

Chaque appel à `resolve()` est tracé via un `DiagnosticAuditRepository`
optionnel (`None` dans les tests qui ne montent pas de base de données —
la traçabilité est un besoin additionnel, jamais une dépendance dure du
pipeline). Une panne d'écriture d'audit ne fait **jamais** échouer la
réponse déjà calculée pour l'utilisateur — même politique que
`escalate_to_ticket` pour `SERVICE_UNAVAILABLE`.

## Les contrats (`contracts.py`)

Miroir Pydantic exact des JSON Schemas versionnés dans
`contracts/diagnostic/v1/` — toute modification d'un schéma doit se
répercuter dans le même changement, des deux côtés.

| Schéma JSON | Classe Pydantic | Sens |
|---|---|---|
| `client-request.schema.json` | `DiagnosticResolveRequest` | Rasa → Diagnostic Engine (`POST /diagnostic/resolve`) |
| `service-invocation-request.schema.json` | `DiagnosticInvocationRequest` | Diagnostic Engine → microservice |
| `service-invocation-response.schema.json` | `ResolvedOutcome` \| `EscalateOutcome` \| `NeedMoreInfoOutcome` | microservice → Diagnostic Engine |
| `capability-manifest.schema.json` | `CapabilityManifest` | auto-description d'un microservice (`GET /diagnostic/manifest`) |

`CapabilityManifest.problems[]` (`ProblemDefinition`) porte, par problème :
un identifiant, un libellé, une description + des phrases d'exemple (pour
le matching sémantique — voir
[7. Classification](07-action-diagnostic-classification.md)), des
mots-clés (repli), l'endpoint à appeler, les champs requis/optionnels/de
repli, et les causes de résolution/escalade possibles.

## Les routes exposées (`router.py`)

- `GET /diagnostic/capabilities` — agrège **tous** les manifestes connus ;
  seule source que le Dialogue Manager consulte pour savoir quels
  (service, problème) sont diagnosticables.
- `POST /diagnostic/resolve` — point d'entrée unique, décrit ci-dessus.
  Identité de l'utilisateur transmise en header `X-User-ID`, jamais dans le
  corps (même convention que Kong → wallet-service). Si le pipeline
  renvoie sa **propre** escalade de résilience (`SERVICE_UNAVAILABLE`), un
  vrai ticket est créé automatiquement via `/diagnostic/escalate`, sans
  attendre de confirmation utilisateur — les escalades décidées par le
  microservice lui-même pour une raison métier restent, elles, soumises à
  confirmation côté Rasa (voir [8. Diagnostic — exécution](08-action-diagnostic-execution.md)).
- `POST /diagnostic/debug/classify` — outil de debug/démo : reproduit le
  calcul de score de base sur **tout** le catalogue, remplace les scripts
  jetables utilisés pendant l'audit de classification.
- `POST /diagnostic/escalate` — relais générique vers le système de
  tickets existant (voir [16. Domaines admin](16-domaines-admin-complaints-feedback-audit.md)),
  réutilisé tel quel plutôt que dupliqué.
