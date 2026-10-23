← [5. Le pipeline NLU de Rasa](05-rasa-nlu-pipeline.md) | → [7. Diagnostic — classification sémantique](07-action-diagnostic-classification.md)

# 6. Rasa Core, policies, domaine

> **Rôle de ce document** : comment Rasa décide **quelle action** exécuter
> une fois l'intention connue — la gestion d'état de la conversation, pas
> la classification elle-même (chapitre 5) ni la logique métier des actions
> (chapitres 7 à 11).

## Les policies

`rasa/config.yml` ne surcharge pas les policies : configuration par défaut
`RulePolicy`, `TEDPolicy`, `MemoizationPolicy`, `UnexpecTEDIntentPolicy`.
Elles décident, à partir de l'intention retenue et de l'**état de
conversation** (slots remplis, formulaire actif ou non), quelle action
personnalisée appeler côté serveur Actions (port 5055).

## Le domaine (`rasa/domain.yml`)

19 intents déclarés : `ask_faq`, `greet`, `goodbye`, `bot_challenge`,
`create_reclamation`, `diagnostic`, `affirm`, `deny`, `out_of_scope`,
`inappropriate_language`, `suggestion`, `plainte`, `ask_capabilities`,
`rate_response`, `browse_faq`, `select_faq`, `ask_complaint_status`,
`request_human_agent`, `cancel_human_agent_request`. (2026-10-23 : `rate_response`
regroupe les avis utile / pas utile, sens porté par l'entité `rating` ; `select_faq`
regroupe le choix d'un thème et d'une question de la FAQ.)

25 actions personnalisées (voir chapitres 7 à 11 pour le détail des plus
importantes) et 1 formulaire, `reclamation_form` (voir
[9. Réclamations](09-action-reclamation-formulaire.md)).

### Entités volontairement retirées

Le domaine documente explicitement pourquoi 6 entités (`category`,
`service`, `device`, `error_type`, `keyword`, `urgency`) ont été retirées :
**zéro exemple annoté** dans `rasa/data/nlu.yml` pour chacune — les
déclarer sans jamais les entraîner laissait croire à une extraction qui
n'existait pas. `device`/`error_type` restent des concepts réels, mais
calculés par similarité sémantique sur texte brut (voir
[7. Diagnostic — classification](07-action-diagnostic-classification.md)),
jamais via une entité Rasa.

### Slots notables

- `category` (catégorique KYC/Wallet/Video/Auth/Chat/Safety) : rempli par
  texte libre uniquement pendant `reclamation_form`, jamais par une entité
  (le mapping `from_entity` a été retiré pour la même raison que ci-dessus —
  0 exemple annoté).
- `description` (texte libre) : **aucune restriction `not_intent`**,
  volontairement — une vraie description de problème peut contenir
  n'importe quel vocabulaire et se faire classer à tort, à très haute
  confiance, dans un intent totalement étranger (exemple documenté : "un
  autre utilisateur me menace, question de sécurité" classé `bot_challenge`
  à 99.99%). Avec une restriction, ce texte serait rejeté et le formulaire
  redemanderait la description en boucle.
- `urgency` : **n'est plus demandée à l'utilisateur** depuis un retour
  utilisateur (2026-07) — ce jugement est désormais déduit automatiquement
  de la description côté serveur (`validate_description`), jamais délégué.
- `diagnostic_state`, `service_candidates`, `pending_field` : l'état du
  diagnostic en cours (voir
  [8. Diagnostic — exécution](08-action-diagnostic-execution.md)).
- 11 anciens slots (payment_method, transaction_id, time, content_type...)
  ont été supprimés après vérification qu'aucun n'était plus réellement
  utilisé — les valeurs du flux diagnostic vivent dans `diagnostic_state`
  (JSON), pas dans des slots Rasa dédiés.

### `reclamation_form.required_slots`

`[description, category, incident_date, cancel_choice, field_to_edit]` —
cette liste statique n'est qu'un défaut : `ValidateReclamationForm.required_slots()`
(voir [9. Réclamations](09-action-reclamation-formulaire.md)) la remplace
entièrement au runtime selon la sous-étape en cours (modification,
annulation...).

## Ce que ce chapitre ne couvre pas

La logique métier exécutée une fois l'action choisie vit dans le serveur
Actions (port 5055) — voir les chapitres 7 à 11.
