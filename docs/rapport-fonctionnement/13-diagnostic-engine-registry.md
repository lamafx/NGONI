← [12. Résilience côté serveur Actions](12-resilience-actions-server.md) | → [14. Diagnostic Engine — pipeline et contrats](14-diagnostic-engine-pipeline-contracts.md)

# 13. Diagnostic Engine — le registre

> **Rôle de ce document** : `app/domains/diagnostic/registry.py`
> (`CapabilityRegistry`) — comment le Diagnostic Engine sait quels
> microservices existent et ce qu'ils savent traiter, **avant** qu'un
> problème ne soit résolu (chapitre 14) ou invoqué (chapitre 15).

## La liste des services vient d'un fichier, pas du code

`fastapi/services_registry.yaml` déclare **quels** microservices existent —
chaque entrée nomme une variable d'environnement pour son URL/secret, jamais
la valeur elle-même (fournie par l'environnement d'exécution). Avant la
Phase 5 du projet, cette liste était codée en dur dans une fonction Python ;
ajouter un service exige aujourd'hui seulement une entrée dans ce YAML, sans
redémarrer le Engine. Un fichier absent, illisible ou mal formé dégrade vers
une liste vide (log un avertissement) plutôt que de faire planter le Engine
au démarrage — cohérent avec la politique de résilience du reste du
Registry.

## Ce qui n'est jamais dupliqué : le contenu des manifestes

Le **contenu** de chaque manifeste (quels problèmes, quels champs) n'est
jamais recopié dans ce fichier YAML — il est récupéré réellement via
`GET {base_url}/diagnostic/manifest` et validé contre le même contrat
Pydantic que celui décrit au [chapitre 14](14-diagnostic-engine-pipeline-contracts.md#capabilitymanifest).
`wallet_stub`/`user_stub` implémentent ce même contrat côté microservice —
c'est pour cela qu'ils suffisent à faire tourner tout le pipeline en
développement sans les vrais `ngoni-wallet-service`/`ngoni-user-service`
(voir [[project-ngoni-diagnostic-stub-scope]]).

## Rafraîchissement périodique, sans redémarrage

`CapabilityRegistry.refresh()` relit **à la fois** la liste des services
(`services_registry.yaml`) et interroge chaque manifeste — un service
injoignable ou renvoyant un manifeste non conforme est simplement ignoré
(log), sans faire échouer tout le registre : un service en panne ne doit
pas empêcher les autres d'être diagnosticables.

`poll_forever()` tourne en tâche de fond pour toute la durée de vie du
process (lancée depuis `app/main.py::startup`, annulée proprement à
l'arrêt) — intervalle par défaut **300 secondes**
(`REGISTRY_POLL_INTERVAL_SECONDS`, remonté depuis 30s utilisé en
développement/soutenance, mise en conformité production). Un nouveau
service ou un nouveau problème est donc pris en compte au plus tard 5
minutes après sa publication, sans redémarrage du Engine.

## Les embeddings sont précalculés ici, pas à chaque message

`_compute_all_embeddings` encode **en un seul appel batché**
(`embed_passage_batch`, exécuté via `asyncio.to_thread` pour ne jamais
bloquer la boucle asyncio) la description + les phrases d'exemple de
**tous** les problèmes du catalogue, à chaque rafraîchissement — jamais à
chaque message utilisateur (voir
[7. Diagnostic — classification](07-action-diagnostic-classification.md)
pour où ces vecteurs précalculés sont ensuite comparés à l'embedding d'un
message). Si le modèle d'embeddings est indisponible, chaque problème reste
routable, juste sans embedding — repli sur les mots-clés côté Rasa pour
celui-ci, jamais un échec total du registre.

## Ce que ce chapitre ne couvre pas

Une fois le registre chargé, la résolution d'un problème précis
(`DiagnosticPipeline.resolve`) et l'invocation HTTP réelle du microservice
sont aux [chapitres 14](14-diagnostic-engine-pipeline-contracts.md) et
[15](15-diagnostic-engine-adapter-circuit-breaker.md).
