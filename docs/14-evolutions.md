← [Sommaire](README.md) | [13. Limitations actuelles](13-limitations.md)

# 14. Perspectives d'évolution

## 14.1 Sécurisation pour la production

En réponse directe aux limitations du [chapitre 13](13-limitations.md) :

- **Authentification utilisateur** : JWT ou OAuth2 sur les endpoints exposés
  à un client final (webhook Rasa, `/faq/*`, `/feedback*`), au minimum pour
  identifier l'appelant sans dépendre du seul `user_id` transmis en clair.
- **Authentification inter-services** : renforcer `X-Internal-Secret` (déjà
  en place) — envisager mTLS ou un token à durée de vie courte plutôt qu'un
  secret statique partagé.
- **HTTPS** partout, y compris entre conteneurs si le déploiement s'étend
  au-delà d'un hôte unique.
- **Rate limiting** par utilisateur/IP sur les endpoints publics.
- **Gestion des secrets** via un coffre-fort dédié (Vault, secret manager du
  fournisseur cloud) plutôt que des fichiers `.env`.

## 14.2 CI/CD

- Mettre en œuvre la recommandation déjà documentée dans
  `contracts/diagnostic/README.md` §6 : valider chaque exemple de contrat
  avec un validateur JSON Schema générique en CI, des deux côtés
  (Python/`jsonschema`, PHP/`justinrainbow/json-schema`).
- Automatiser `rasa test nlu`/`rasa test` en CI sur chaque changement de
  `rasa/data/*.yml`, avec un seuil de non-régression sur les métriques par
  intention.
- Automatiser `pytest fastapi/tests/` en CI.

## 14.3 Étendre le Capability Registry aux microservices réels

Le contrat de diagnostic est déjà indépendant du langage et de
l'implémentation (JSON Schema autonome) : la bascule des stubs
(`wallet_stub`, `user_stub`) vers `ngoni-wallet-service`/`ngoni-user-service`
réels ne nécessite qu'un changement de configuration côté
`services_registry.yaml`, **dès lors que ces services implémentent
eux-mêmes** `GET /diagnostic/manifest` et leurs endpoints de résolution
(état d'avancement à suivre dans `contracts/diagnostic/README.md` §8).

## 14.4 Montée en charge

- **Catalogue de diagnostic** : si le nombre de problèmes diagnosticables
  grossit significativement (plusieurs dizaines de services), revisiter la
  boucle de scoring en Python pur (`_score_capabilities_embeddings`) au
  profit d'une version vectorisée (numpy), en précalculant les matrices une
  seule fois par rafraîchissement du cache plutôt qu'à chaque message — voir
  la mesure comparative déjà documentée dans `rasa/actions/diagnostic.py`
  (la version numpy actuelle serait une régression au volume présent, mais
  deviendrait avantageuse au-delà de ~100-200 problèmes).
- **Réplication** : plusieurs instances du moteur FastAPI derrière un
  répartiteur de charge, Rasa Core éventuellement scalé horizontalement
  (le tracker store SQL le permet déjà, contrairement à un tracker en
  mémoire).
- **File d'attente** pour les tâches de fond actuellement en
  `BackgroundTasks` FastAPI (ex. `FaqService.enqueue_faq_batch`), si le
  volume le justifie.

## 14.5 Observabilité centralisée

`DiagnosticSession`/`DiagnosticAuditLog` fournissent déjà la donnée brute
nécessaire à un tableau de bord de suivi (taux de résolution automatique vs
escalade, latence par service, problèmes les plus fréquents) — reste à
construire la couche de visualisation. Centraliser les logs des différents
processus (aujourd'hui dispersés entre fichiers locaux et `docker compose
logs`) vers un système unique (Loki, ELK, ou équivalent) faciliterait le
diagnostic incident, notamment la corrélation par `trace_id` déjà présente
dans le format de log.

## 14.6 Nouvelles fonctionnalités envisageables

- **Support multilingue** : entraîner/évaluer un pipeline NLU par langue, ou
  migrer vers un featurizer multilingue avec un seul modèle.
- **Nouveaux domaines diagnosticables** au-delà de wallet/user (vidéo,
  authentification...), en suivant la procédure de
  [11.4](11-maintenance.md#114-rendre-un-nouveau-microservice-diagnosticable).
- **Tableau de bord agent humain** pour le suivi des tickets créés
  (`complaints`), aujourd'hui consultables uniquement via l'API ou pgAdmin.

---

Suite : [15. Modèle de données](15-modele-donnees.md)
