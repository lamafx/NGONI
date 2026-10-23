← [Sommaire](README.md)

# 1. Présentation générale

## 1.1 Contexte

NGONI est une plateforme (réseau social / services financiers : portefeuille,
cadeaux, boost, retraits, KYC — voir les microservices `ngoni-wallet-service`
et `ngoni-user-service`) dont les utilisateurs rencontrent des besoins
récurrents de support : comprendre une fonctionnalité, signaler un problème
sur une opération (ex. retrait bloqué), ou simplement poser une question sur
le fonctionnement du service.

L'assistant conversationnel documenté ici répond à ce besoin de premier
niveau, sans intervention humaine dans le cas général, en s'appuyant sur deux
briques complémentaires :

- un **bot conversationnel** (Rasa) qui comprend le langage naturel en
  français et pilote le dialogue ;
- un **moteur applicatif** (FastAPI) qui porte la logique métier — recherche
  de FAQ, diagnostic de problèmes auprès des microservices concernés,
  création de réclamations, collecte de feedback.

## 1.2 Objectif du système

Offrir un point d'entrée conversationnel unique capable de :

1. **Répondre aux questions fréquentes** par recherche sémantique plutôt que
   par mots-clés exacts (ex. "mon compte es bloké" doit trouver la FAQ sur le
   blocage de compte malgré la faute de frappe).
2. **Diagnostiquer un problème réel** en interrogeant en direct le
   microservice concerné (ex. état d'un retrait), plutôt que de renvoyer une
   réponse générique déconnectée de l'état réel du compte de l'utilisateur.
3. **Escalader vers un humain** (création automatique d'un ticket) quand le
   diagnostic ne peut pas résoudre le problème seul, ou quand le
   microservice cible est injoignable.
4. **Filtrer les messages hors-sujet ou inappropriés** avant qu'ils ne soient
   mal interprétés par le modèle de classification d'intention.
5. **Recueillir le feedback** des utilisateurs (utile / pas utile,
   suggestions, plaintes) pour améliorer le service dans le temps.

## 1.3 Cas d'utilisation

| Scénario | Intention Rasa | Composant traitant | Résultat typique |
|---|---|---|---|
| "Comment fonctionne le parrainage ?" | `ask_faq` | Recherche sémantique FAQ (`/faq/search`) | Réponse directe, sans intervention humaine |
| "Mon retrait est bloqué depuis hier" | `diagnostic` | Diagnostic Engine → `wallet-service` | `RESOLVED` (cause identifiée et expliquée), `ESCALATE` (ticket créé) ou `NEED_MORE_INFO` |
| "Je veux signaler un problème" | `create_reclamation` / `plainte` | Formulaire de réclamation → Complaints | Ticket `CMP-YYYYMMDD-XXXXXXXX` créé et communiqué à l'utilisateur |
| "fuck ce bot est nul" | `inappropriate_language` (via le garde-fou vocabulaire) | Réponse de recadrage, pas de faux intent métier | Pas de FAQ ni de diagnostic déclenché à tort |
| Clic sur "pas utile" après une réponse | `rate_response_not_useful` | Feedback (`ResponseRating`) | Note enregistrée, éventuellement liée à un ticket de suivi |
| "Que sais-tu faire ?" | `ask_capabilities` | `action_describe_capabilities` | Liste des capacités, alimentée dynamiquement par le Capability Registry pour la partie diagnostic |

## 1.4 Fonctionnalités principales

- **FAQ sémantique** : recherche par similarité d'embeddings (et non par
  correspondance exacte), résistante aux fautes de frappe et aux
  reformulations ; navigation par catégorie (`browse_faq`,
  `select_faq_category`, `select_faq_question`).
- **Moteur de diagnostic dynamique (Capability Registry)** : la liste des
  problèmes diagnosticables n'est pas codée en dur côté bot — elle est
  découverte à l'exécution en interrogeant le manifeste de chaque
  microservice enregistré (`services_registry.yaml`). Ajouter un problème
  diagnosticable dans un microservice le rend immédiatement disponible dans
  le bot, sans redéploiement du moteur ni du bot.
- **Escalade automatique** : un ticket est créé sans confirmation
  supplémentaire de l'utilisateur si le microservice cible est injoignable
  (`SERVICE_UNAVAILABLE`) ou si le diagnostic conclut à une escalade.
- **Réclamations et suggestions** : formulaire guidé (catégorie, description,
  urgence...) aboutissant à un ticket traçable.
- **Feedback structuré** : notation des réponses (utile / pas utile),
  suggestions et plaintes, chacune pouvant générer un ticket de suivi.
- **Garde-fou de vocabulaire** (`components/vocabulary_guard.py`) :
  composant NLU personnalisé qui empêche le classifieur d'intention
  d'assigner, avec une confiance artificiellement élevée, une intention
  connue à un message hors-vocabulaire (insultes, texte aléatoire) — voir
  [07-integration-ia.md](07-integration-ia.md) pour le détail technique.

## 1.5 Public visé par ce document

- **Développeurs backend** (Python/FastAPI, Rasa) amenés à faire évoluer le
  moteur ou le bot.
- **Mainteneurs** chargés du déploiement, de la supervision ou du dépannage
  en environnement de développement.
- **Équipes microservices** (wallet, user, et futures équipes) souhaitant
  rendre leur service diagnosticable par l'assistant, via le contrat décrit
  dans [`contracts/diagnostic/README.md`](../contracts/diagnostic/README.md).

Ce document suppose une familiarité de base avec Rasa, FastAPI et les
architectures microservices ; il ne réexplique pas ces outils en soi, mais
la façon dont ils sont assemblés et utilisés dans ce projet.

## 1.6 Glossaire

| Terme | Définition |
|---|---|
| **Diagnostic Engine** | Sous-système FastAPI (`app/domains/diagnostic`) qui orchestre la résolution d'un problème signalé : sélection du microservice concerné, appel, interprétation de la réponse, décision `RESOLVED` / `ESCALATE` / `NEED_MORE_INFO`. |
| **Capability Registry** | Registre en mémoire, construit en interrogeant périodiquement `/diagnostic/manifest` de chaque microservice listé dans `services_registry.yaml`. Source unique de vérité sur ce qui est diagnosticable. |
| **Manifest** (manifeste de capacités) | Document exposé par un microservice sur `GET /diagnostic/manifest`, listant les problèmes qu'il sait diagnostiquer, leurs champs requis et leurs libellés. Conforme à `capability-manifest.schema.json`. |
| **`problem_id`** | Identifiant `snake_case` d'un problème diagnosticable (ex. `withdrawal_pending`), déclaré par un microservice dans son manifeste. |
| **Escalade** | Décision de créer un ticket de support humain plutôt que de résoudre automatiquement — soit parce que le microservice le décide explicitement, soit parce qu'il est injoignable. |
| **Service** | Implémentation minimale d'un microservice (`fastapi/user_service`, `fastapi/wallet_service`), utilisée en développement local pour simuler `wallet-service` / `user-service` sans dépendre des vrais services. |
| **DIETClassifier** | Modèle de classification d'intention et de reconnaissance d'entités utilisé par le pipeline NLU de Rasa (voir [07-integration-ia.md](07-integration-ia.md)). |
| **Action server** | Processus Rasa séparé (`rasa/actions`) qui exécute le code Python personnalisé (`Action.run`) déclenché par le dialogue — c'est lui qui appelle le moteur FastAPI. |
| **Vocabulary guard** | Composant NLU personnalisé qui abaisse artificiellement la confiance du DIETClassifier quand aucun mot du message n'est reconnu, pour laisser le `FallbackClassifier` s'appliquer correctement. |

---

Suite : [2. Architecture globale](02-architecture.md)
