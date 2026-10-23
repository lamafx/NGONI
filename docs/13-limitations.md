← [Sommaire](README.md) | [12. Journalisation et supervision](12-logs-supervision.md)

# 13. Limitations actuelles

Ce chapitre liste explicitement ce qui n'est **délibérément pas fait** à ce
stade du projet, et pourquoi. Ce sont des choix assumés pour un
environnement de développement/recherche local, **pas des oublis** — mais
ils bloquent tous un déploiement au-delà de cet environnement sans y être
adressés (voir [14. Perspectives d'évolution](14-evolutions.md)).

## 13.1 Absence d'authentification et d'autorisation

Aucun endpoint du périmètre assistant (FastAPI, Rasa, services wallet/user)
n'est protégé par une authentification utilisateur — à l'exception du
module admin de `ngoni-core-service` (`assertInternalAuth`) et du header
`X-Internal-Secret` déjà en place entre le moteur et les microservices de
diagnostic (une authentification de service, pas d'utilisateur final).

**Pourquoi** : choix délibéré pour ce stade de développement — pas de
gestion de clés/tokens à mettre en place pour itérer et tester rapidement.

**Socle déjà en place pour les futures routes admin** (`app/shared/admin_auth.py`) :
une dépendance FastAPI `require_admin_auth` (header `X-Internal-Secret`,
fermée par défaut si `ADMIN_INTERNAL_SECRET` n'est pas configuré) et
`get_admin_id` (header `X-User-ID`, traçabilité), suivant exactement le
même patron que `assertInternalAuth`/`getAdminId` de `ngoni-core-service`.
Introduit **avant** la première route admin plutôt qu'ajouté après coup, un
avertissement au démarrage du moteur (`main.py::startup`) signale si le
secret n'est pas configuré.

**Première route admin** : `/admin/complaints` (gestion des tickets —
lister, consulter, changer le statut), voir
[6.3](06-api-reference.md#gestion-admin-des-tickets--admincomplaints) et
[15.3](15-modele-donnees.md#153-schéma-complaints--tickets). Protégée par
`require_admin_auth` dès son introduction. Le reste du périmètre (FAQ,
diagnostic, feedback, Rasa) reste sans authentification — cette limitation
n'est donc levée que pour la gestion des tickets, pas pour l'ensemble de
l'assistant.
**Pas** une recommandation pour la production.

## 13.2 Absence de chiffrement des échanges

Tous les échanges HTTP de ce périmètre sont en clair (`http://`, pas
`https://`) — cohérent avec un environnement 100 % local où aucun trafic ne
quitte la machine de développement.

## 13.3 Secrets en clair dans les variables d'environnement

`WALLET_SERVICE_INTERNAL_SECRET`, `USER_SERVICE_INTERNAL_SECRET`, les
identifiants PostgreSQL : de simples valeurs dans des fichiers `.env` non
commités, sans rotation ni coffre-fort de secrets (Vault, AWS Secrets
Manager...). Valeur de développement observée par défaut :
`WALLET_SERVICE_INTERNAL_SECRET=test-secret`.

## 13.4 Pas de limitation de débit (rate limiting)

Aucun endpoint n'impose de quota par utilisateur/IP. Un seul garde-fou
existe contre l'épuisement de ressources : des plafonds de longueur sur les
champs libres (`MAX_MESSAGE_LENGTH`, `MAX_FIELD_ANSWER_LENGTH`, voir
[9.5](09-configuration.md#95-paramètres-modifiables-sans-redéploiement)) —
ce n'est pas une protection contre un afflux de requêtes.

## 13.5 Portée mono-langue

Le pipeline NLU (`DIETClassifier`, `vocabulary_guard`) est entraîné et
calibré exclusivement en français. Un message dans une autre langue serait
traité comme hors-vocabulaire (fallback), pas correctement compris.

## 13.6 Pas de validation automatisée du contrat en CI

`contracts/diagnostic/README.md` (§6) recommande explicitement d'ajouter une
étape de CI qui valide chaque fixture d'exemple avec un validateur JSON
Schema générique (`jsonschema` côté Python, `justinrainbow/json-schema` côté
PHP), pour détecter toute dérive entre le schéma versionné et son miroir
Pydantic sans dépendre uniquement des modèles applicatifs. **Cette étape
n'existe pas encore.**

## 13.7 Pas de haute disponibilité ni de montée en charge testée

Une seule instance de chaque composant, sans réplication ni équilibrage de
charge. Le catalogue de diagnostic reste volontairement restreint (8
problèmes au moment de la rédaction) ; plusieurs seuils de classification
ont été calibrés empiriquement sur ce volume et le raisonnement même
derrière la boucle Python de scoring (non vectorisée, voir
[7. Intégration des modèles IA](07-integration-ia.md)) suppose un petit
catalogue — un changement d'échelle significatif nécessiterait une
réévaluation, pas seulement plus de ressources matérielles.

## 13.8 Divergences constatées entre code et documentation existante

`contracts/diagnostic/README.md` (§8, "État d'implémentation") indique, au
moment de la rédaction de cette documentation, que le pipeline du
Diagnostic Engine est "non implémenté" — alors que
`app/domains/diagnostic/pipeline.py`, `registry.py`, `adapter.py`,
`escalation.py` et les services `wallet_service`/`user_service` existent et sont
fonctionnels. Cette documentation technique (chapitres 1 à 12) reflète
l'état réel du code observé ; le tableau du contrat mériterait une mise à
jour dans le même esprit pour éviter toute confusion future.

---

Suite : [14. Perspectives d'évolution](14-evolutions.md)
