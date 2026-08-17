← [7. Diagnostic — classification sémantique](07-action-diagnostic-classification.md) | → [9. Réclamations — le formulaire](09-action-reclamation-formulaire.md)

# 8. Diagnostic — exécution de l'action

> **Rôle de ce document** : ce qui se passe une fois qu'un problème est
> identifié (chapitre 7) — l'appel réel au Diagnostic Engine, la gestion
> des champs manquants, et la décision d'escalade. Pas l'algorithme de
> classification lui-même (chapitre 7), ni le Diagnostic Engine côté
> FastAPI qui reçoit cet appel (chapitres 13 à 15).

## Une seule action, pas quatre

`ActionRunDiagnosticStep` consolide en **une seule** action Rasa ce qui
était auparavant 4 actions chaînées par une règle (classifier → extraire →
mettre à jour l'état → poser la question suivante/résoudre).

> **Pourquoi la fusion ?** Constaté en pratique : quand 4 actions distinctes
> sont chaînées dans une règle, Rasa réévalue **toutes** les policies à
> chaque étape — `RulePolicy` n'a pas la priorité garantie jusqu'au bout.
> Après 2-3 étapes, `TEDPolicy` proposait une prédiction concurrente plus
> confiante et rejouait une étape une 2ᵉ fois avant la fin de la règle. Une
> seule action = une seule prédiction par tour = moins de concurrence
> possible. Un filet de sécurité complémentaire
> (`_already_ran_since_last_user_message`) ignore une 2ᵉ exécution
> résiduelle sans nouveau message utilisateur entre les deux.

## Déroulé d'un tour

1. **État courant** : lu depuis le slot `diagnostic_state` (JSON) — un slot
   corrompu ne fait jamais planter l'action, l'état repart vide.
2. **Garde-fou bouton "Lancer un diagnostic"** : un clic envoie `/diagnostic`
   sans texte réel — sans ce garde, un texte vide descendait directement
   dans la classification, qui ne trouvait évidemment rien et proposait
   *immédiatement* la création d'un ticket avant même que l'utilisateur
   n'ait décrit quoi que ce soit.
3. **Retrait du préambule de politesse** (`_strip_greeting_preamble`,
   [chapitre 7](07-action-diagnostic-classification.md)) avant toute
   classification.
4. **Clôture spontanée** : si un diagnostic est en cours et que le message
   ressemble à "c'est bon, ça remarche" (`_looks_like_resolution`), le
   diagnostic se ferme avec un accusé de réception, sans appel au moteur.
5. **Classification** (fraîche ou extraction d'une réponse à un champ déjà
   demandé — voir [chapitre 7](07-action-diagnostic-classification.md)).
6. **Verrouillage** du problème choisi dans l'état (`service_id`,
   `template_id`, `required_fields`, `field_specs`...), avec capture
   opportuniste des entités déjà présentes dans le même message (une
   réponse peut contenir plusieurs champs à la fois).
7. **Décision** : champ encore manquant → question posée
   (`_respond_field_question` — texte dynamique construit à partir du
   manifeste, jamais un slot Rasa dédié par champ) ; aucun problème
   identifié → `_respond_no_capability_matched` (proposition de créer un
   ticket) ; tout collecté → `_respond_engine_outcome` (ci-dessous).
8. **Question FAQ résiduelle** : si le message contenait aussi une question
   distincte marquée par un point d'interrogation en fin de phrase, une
   réponse FAQ est ajoutée **en complément silencieux**, jamais à la place
   de la réponse principale.

## L'appel réel au Diagnostic Engine (`_call_diagnostic_engine`)

```python
POST {DIAGNOSTIC_SERVICE_URL}   # http://fastapi:8000/diagnostic/resolve
{
  "session_id": tracker.sender_id,
  "service": state["service_id"],
  "problem": state["template_id"],
  "entities": {...}              # uniquement les champs confirmés
}
headers: { "X-User-ID": tracker.sender_id }
```

Deux familles d'échec sont **distinguées explicitement**, jamais confondues :

- **Panne technique** (timeout, erreur réseau, erreur HTTP) → `{"outcome": "_ENGINE_UNAVAILABLE"}`
  — jamais présenté comme une décision métier. Vérifié en pratique : sans
  cette distinction, une panne transitoire se présentait à l'utilisateur
  exactement comme si son dossier avait réellement été examiné puis
  escaladé.
- **Décision métier réelle** (`RESOLVED` / `ESCALATE` / `NEED_MORE_INFO` —
  voir [14. Pipeline et contrats](14-diagnostic-engine-pipeline-contracts.md))
  → traitée par `_respond_engine_outcome`.

Les entités du payload ne sont **jamais** loggées en cas d'échec (peuvent
contenir des données sensibles — montant, référence de transaction).

## Mode Super-Agent

`_respond_engine_outcome` vérifie `is_superagent_mode(tracker)`
([chapitre 6](06-rasa-core-policies-domain.md) pour le mécanisme de
transport via `metadata`). Un résultat normalement présenté comme une
simple **information** à l'agent standard (ex. "votre dossier KYC est en
cours d'examen", l'utilisateur attend) peut, en mode Super-Agent, déclencher
une **action directe** au lieu d'attendre — cette décision est tracée dans
`audit.agent_actions` sous le domaine dédié `diagnostic_superagent`, distinct
de `diagnostic_classification` (voir
[16. Domaines admin](16-domaines-admin-complaints-feedback-audit.md)),
précisément parce que le niveau de risque est différent : une classification
n'agit jamais seule, une décision Super-Agent le fait.

## Escalade automatique en cas de panne du microservice

Si le Diagnostic Engine lui-même renvoie `ESCALATE` avec
`escalation_reason: SERVICE_UNAVAILABLE` (le microservice métier, ex.
`wallet_stub`, était injoignable — voir
[15. Adapter et disjoncteur](15-diagnostic-engine-adapter-circuit-breaker.md)),
un ticket est créé **automatiquement côté FastAPI**, sans confirmation
utilisateur (voir [14. Pipeline et contrats](14-diagnostic-engine-pipeline-contracts.md)).
Les escalades décidées par le microservice lui-même pour une vraie raison
métier (ex. `ACCOUNT_FROZEN`, `TRANSACTION_NOT_FOUND`) continuent, elles, de
passer par la confirmation explicite gérée ici côté Rasa
(`ActionDecideEscalation`) — ce n'est pas une politique générique du moteur,
donc pas sa responsabilité de l'automatiser.
