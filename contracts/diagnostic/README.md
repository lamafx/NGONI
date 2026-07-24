# Contrat du Moteur de Diagnostic NGONI — v1

Ce dossier est la **source de vérité unique** des échanges entre le Diagnostic Engine et les
microservices métier. Il ne contient aucune logique métier — uniquement la forme des messages
échangés. Toute équipe (wallet, video, auth...) qui souhaite rendre son service diagnosticable
par le chatbot doit implémenter ce contrat, indépendamment du langage utilisé (PHP, Python, ...).

Voir aussi : [docs/diagnostic-flow.md](../../docs/diagnostic-flow.md) (vue d'ensemble du flux) et
[docs/diagnostic-roadmap.md](../../docs/diagnostic-roadmap.md) (plan de développement).

## 1. Portée et exigence de conformité

Un microservice est considéré "diagnosticable" s'il expose, et un seul et unique client
(le Diagnostic Engine) les consomme :

| Route | Méthode | Contrat | Obligatoire |
|---|---|---|---|
| `/diagnostic/manifest` | `GET` | `capability-manifest.schema.json` | Oui — condition d'entrée dans le Capability Registry |
| `/diagnostic/{problem_id}` | `POST` | Requête : `service-invocation-request.schema.json` / Réponse : `service-invocation-response.schema.json` | Oui, un endpoint par `problem_id` déclaré dans le manifeste |

Le Diagnostic Engine, lui, expose au Dialogue Manager (Rasa) :

| Route | Méthode | Contrat |
|---|---|---|
| `/diagnostic/resolve` | `POST` | Requête : `client-request.schema.json` / Réponse : `service-invocation-response.schema.json` (relayée telle quelle) |

Un service qui ne respecte pas ces schémas ne peut pas être ajouté au Registry : la validation
du manifeste au chargement (voir §6) est un pré-requis bloquant, pas une simple recommandation.

## 2. Convention de nommage des URLs

- Toutes les routes de diagnostic sont préfixées par `/diagnostic/`, jamais mélangées avec les
  routes métier classiques (`/wallet/withdraw`, `/gift/send`, etc.), pour qu'un reverse-proxy ou
  une politique de sécurité puisse les isoler facilement (ex: n'autoriser ces routes qu'avec le
  header interne, cf §5).
- `problem_id` est toujours en `snake_case`, sans le nom du service en préfixe (le service est
  déjà porteur de son propre `base_url` / namespace) : `withdrawal_pending`, pas
  `wallet_withdrawal_pending`.
- Le chemin d'un problème est le `problem_id` tel quel ou une forme courte cohérente
  (`/diagnostic/withdrawal`, `/diagnostic/topup`, `/diagnostic/gift`) — la valeur exacte du
  chemin est libre, elle est de toute façon déclarée explicitement dans `endpoint.path` du
  manifeste et jamais déduite par convention côté Engine. **Le manifeste fait foi, pas l'URL.**

## 3. Versionnement et compatibilité

Deux versions coexistent et ne doivent pas être confondues :

- **Version du dossier de contrat** (`contracts/diagnostic/v1/`) : bump uniquement en cas de
  changement incompatible de l'enveloppe elle-même (ex: renommer `outcome` en `status`). Un tel
  changement crée un nouveau dossier `v2/` ; `v1/` reste servi pendant la période de transition.
- **`manifest_version`** (champ du manifeste, SemVer `MAJOR.MINOR.PATCH`) : propre à chaque
  service, incrémentée à chaque évolution de son propre manifeste (ajout d'un problème, ajout
  d'un champ optionnel, etc.).

Règles de compatibilité ascendante (principe de robustesse de Postel — *"be conservative in
what you send, be liberal in what you accept"*) :

- **Autorisé sans bump majeur** : ajouter un problème, ajouter un champ optionnel, ajouter une
  valeur à un tableau `keywords`/`resolution_causes`/`escalation_causes`.
- **Interdit sans bump majeur du dossier de contrat** : renommer/supprimer un champ existant,
  changer le type d'un champ, retirer une valeur de `oneOf`/`enum` déjà utilisée en production.
- Le Diagnostic Engine et tous les clients doivent **ignorer silencieusement tout champ inconnu**
  reçu (ne jamais faire de validation `additionalProperties: false` côté *lecture* applicative,
  même si les schémas eux-mêmes sont stricts pour la validation en CI). Cela permet à un service
  d'ajouter un champ avant que le Engine ne sache l'exploiter, sans rien casser.

## 4. Ce que le contrat ne décrit pas (et pourquoi)

Volontairement absents de ce contrat : les seuils métier (ex: durée d'attente avant escalade),
les règles de KYC, les taux de conversion, etc. Ces éléments vivent exclusivement dans le code
de chaque microservice. Les blocs `resolution_causes` / `escalation_causes` du manifeste sont
**déclaratifs et documentaires** (utiles pour l'audit, les tableaux de bord, la génération de
FAQ) — ils ne sont jamais évalués ni interprétés par le Diagnostic Engine. Le Engine ne fait que
transporter les décisions déjà prises par le microservice (voir `docs/diagnostic-flow.md`, §
"Résolution & escalade — qui décide, qui documente").

## 5. Sécurité des échanges

- Toutes les routes `/diagnostic/*` (manifeste et invocation) sont des routes **internes**,
  jamais exposées publiquement. Elles doivent être protégées par le même mécanisme que celui déjà
  en place côté wallet-service : header `X-Internal-Secret` validé contre un secret partagé
  (voir `ngoni-wallet-service/app/Http/Middleware/InternalAuth.php`).
- Chaque appel du Diagnostic Engine vers un microservice porte un header `X-Request-ID` (valeur
  identique au `trace_id` de la requête), à des fins de corrélation dans les logs des deux côtés.
- Aucune donnée d'authentification utilisateur (mot de passe, token de session brut) ne doit
  jamais transiter dans `entities` ou `context` : seul `user_id` (déjà résolu) y figure.

## 6. Validation et tests de contrat

- Chaque schéma de `v1/` est **autonome** (aucun `$ref` inter-fichiers) afin de rester
  validable indépendamment dans n'importe quel langage, sans nécessiter de résolveur de schémas
  partagé entre l'écosystème Python (FastAPI) et l'écosystème PHP (Laravel/wallet-service).
- Le sous-dossier `v1/examples/valid/` contient un exemple conforme par schéma ; `v1/examples/invalid/`
  contient des cas volontairement non conformes, catalogués dans son propre `README.md`.
- Côté FastAPI, ces exemples sont utilisés comme fixtures de test (`fastapi/tests/test_diagnostic_contracts.py`)
  contre le miroir Pydantic (`fastapi/app/domains/diagnostic/contracts.py`), qui doit rester
  synchronisé manuellement avec les fichiers `.schema.json` de ce dossier.
- Recommandation pour la suite du projet (Phase 6 de la roadmap) : ajouter une étape de CI qui
  valide chaque fixture avec un validateur JSON Schema générique (`jsonschema` côté Python,
  `justinrainbow/json-schema` côté PHP) pour détecter toute dérive entre les deux implémentations
  sans dépendre uniquement des modèles Pydantic.

## 7. Processus de changement

1. Toute modification d'un fichier `.schema.json` de ce dossier doit être accompagnée d'au moins
   un exemple valide et, si une règle de validation change, d'un exemple invalide correspondant.
2. Le miroir Pydantic (`contracts.py`) et les tests associés doivent être mis à jour dans la même
   proposition de changement — un schéma et son miroir ne doivent jamais diverger.
3. Un changement incompatible (voir §3) implique la création d'un nouveau dossier de version et
   ne doit jamais modifier `v1/` rétroactivement.

## 8. État d'implémentation

| Service | Manifeste exposé | Endpoints de diagnostic | Statut |
|---|---|---|---|
| wallet-service | Non | Non | À faire (Phase 1 de la roadmap) |
| video-service | Non | Non | Non planifié |
| auth-service | Non | Non | Non planifié |
| Diagnostic Engine (FastAPI) | — | `/diagnostic/resolve` (à faire) | Contrats définis (ce dossier), pipeline non implémenté |
