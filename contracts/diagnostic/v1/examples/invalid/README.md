# Fixtures invalides — catalogue

Ces fichiers sont volontairement non conformes aux schémas. Ils servent de tests négatifs
(`tests/test_diagnostic_contracts.py`) pour prouver que la validation rejette bien les cas
qu'elle doit rejeter, pas seulement qu'elle accepte les cas valides.

| Fichier | Schéma visé | Violation | Règle du schéma concernée |
|---|---|---|---|
| `service-invocation-response.missing_message.json` | `service-invocation-response.schema.json` | Le champ `message` est absent alors qu'il est obligatoire pour l'outcome `RESOLVED`. | `$defs.resolved.required` |
| `service-invocation-response.unknown_outcome.json` | `service-invocation-response.schema.json` | La valeur `"IN_PROGRESS"` n'existe dans aucune des 3 variantes du `oneOf` (`RESOLVED`, `ESCALATE`, `NEED_MORE_INFO`). | `oneOf` |
| `client-request.bad_problem_id.json` | `client-request.schema.json` | `service` et `problem` contiennent des majuscules/tirets, alors que la convention impose du snake_case strict. | `properties.service.pattern`, `properties.problem.pattern` |
| `capability-manifest.missing_endpoint.json` | `capability-manifest.schema.json` | La définition du problème `withdrawal_pending` n'a pas de bloc `endpoint`, pourtant obligatoire pour que le Diagnostic Engine sache où router l'appel. | `$defs.problemDefinition.required` |

Toute contribution ajoutant une nouvelle règle de validation dans un schéma doit s'accompagner
d'au moins une fixture invalide correspondante ici, pour garder les tests de contrat représentatifs.
