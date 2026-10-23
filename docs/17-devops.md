← [Sommaire](README.md) | [16. Audit qualité NLU + FAQ retrieval](16-audit-faq-nlu-2026-07.md)

# 17. DevOps — flow Rasa

> **Périmètre de ce chapitre** : exclusivement le cycle DevOps du **flow
> Rasa** (conteneurs `rasa` et `actions` — NLU/Core, entraînement, tests,
> build, déploiement, CI/CD). Il ne couvre pas l'ordre de démarrage complet
> du moteur FastAPI ni des services (voir [10. Déploiement](10-deploiement.md))
> et **ne couvre volontairement aucune brique LLM** : les pistes d'évolution
> vers un LLM générique (re-ranking, RAG) restées au stade de recommandation
> — voir [16. Audit qualité NLU + FAQ retrieval §5](16-audit-faq-nlu-2026-07.md)
> et [14. Perspectives d'évolution §14.6](14-evolutions.md#146-nouvelles-fonctionnalités-envisageables)
> — ne font partie d'aucune étape opérationnelle décrite ici : ce projet
> n'exécute aujourd'hui aucun LLM en production, uniquement le pipeline Rasa
> (`DIETClassifier`) et le modèle d'embeddings `sentence-transformers` (voir
> [7.1](07-integration-ia.md#71-vue-densemble), ni l'un ni l'autre n'étant un
> LLM génératif).

## 17.1 Composants conteneurisés

| Conteneur | Image de base | Source | Port | Volumes |
|---|---|---|---|---|
| `rasa` | `rasa/rasa:3.6.20` | `rasa/Dockerfile` | `5005` | `./rasa:/app`, `./rasa/models:/app/models` |
| `actions` | `rasa/rasa-sdk:3.6.2` | `rasa/actions/Dockerfile` | `5055` | `./rasa/actions:/app/actions` |

Le `Dockerfile` de `rasa` fige `transformers==4.26.0` et `sentencepiece`
(requis par `LanguageModelFeaturizer`, utilisé uniquement dans
`config-embedding-experiment.yml`, une configuration expérimentale non
utilisée en pratique — voir [7.2](07-integration-ia.md#72-modèle-nlu-dietclassifier)
pour le pipeline réellement actif) — installés à la construction de l'image
pour survivre à un rebuild.

Build ciblé (sans toucher aux autres services de `docker-compose.yml`) :

```powershell
docker compose build rasa actions
```

## 17.2 Cycle de vie d'un modèle Rasa (build → train → test → deploy → rollback)

1. **Entraîner** :
   ```powershell
   docker compose run --rm rasa train
   ```
   Produit un nouvel artefact versionné `rasa/models/<timestamp>-<nom>.tar.gz`.

2. **Évaluer** — ne jamais déployer une régression silencieuse :
   ```powershell
   docker compose exec rasa rasa test nlu --out results
   docker compose exec rasa rasa test
   ```
   `rasa test nlu` compare aux exemples de `rasa/tests/test_nlu.yml`
   (matrice de confusion, histogramme, rapport JSON par intention) ;
   `rasa test` rejoue les parcours de `rasa/tests/test_stories.yml`. Comparer
   le rapport JSON obtenu à celui du modèle actuellement en place, intention
   par intention.

3. **Déployer** — Rasa charge automatiquement le `.tar.gz` le plus récent du
   dossier `models/` au démarrage :
   ```powershell
   docker compose restart rasa
   ```

4. **Rollback** — conserver systématiquement l'ancien `.tar.gz` dans
   `rasa/models/` : en cas de régression constatée en usage réel, le
   supprimer (ou déplacer le nouveau) puis `docker compose restart rasa`
   suffit à revenir en arrière, sans réentraînement.

Détail complet et rationale : [7.8](07-integration-ia.md#78-déploiement-dun-nouveau-modèle-rasa-en-production).

## 17.3 Démarrage / arrêt (flow Rasa seul)

```powershell
docker compose up -d rasa actions
docker compose logs -f rasa actions
docker compose stop rasa actions
```

Vérification post-démarrage :

| Vérification | Commande | Attendu |
|---|---|---|
| Modèle chargé | `curl http://localhost:5005/status` | `model_file` non vide |
| Action server joignable | `docker compose exec rasa curl http://actions:5055/health` | `{"status": "OK"}` |

Le moteur FastAPI dépend de Rasa au démarrage (`wait_for_rasa()`) — voir
[10.4](10-deploiement.md#104-ordre-de-démarrage-recommandé) pour l'ordre de
démarrage complet incluant le moteur et les services, hors périmètre de ce
chapitre.

## 17.4 Logs et supervision du flow Rasa

```powershell
docker compose logs -f rasa
docker compose logs -f actions
```

L'action server journalise les décisions de classification diagnostique
(`_score_capabilities*`) et les échecs d'appel réseau vers le moteur FastAPI
(repli fonctionnel, toujours dignes d'investigation si répétés) — voir
[12.2](12-logs-supervision.md#122-logs-rasa--actions). Aucun agrégateur
centralisé (ELK/Loki) n'est en place à ce stade — voir
[12.5](12-logs-supervision.md#125-limites-actuelles-de-supervision).

## 17.5 CI/CD — état actuel et pipeline proposé

**État actuel : aucune CI/CD n'existe pour `ngoni-ia-service`**, contrairement
aux autres services de la plateforme (`ngoni-admin-service`,
`ngoni-user-service`, `ngoni-client-backoffice`, qui disposent chacun d'un
`.gitlab-ci.yml`). Confirmé par [13.6](13-limitations.md#136-pas-de-validation-automatisée-du-contrat-en-ci)
et recommandé par [14.2](14-evolutions.md#142-cicd).

Proposition de pipeline, **limitée au flow Rasa** (le moteur FastAPI et ses
services relèveraient d'un job séparé, hors périmètre de ce chapitre), sur le
modèle des pipelines GitLab CI déjà en place ailleurs sur la plateforme
(registre `registry.gitlab.com/ngoni_ci/microservices`, déploiement par
script SSH) — **non implémentée, à titre d'illustration** :

```yaml
stages:
  - test
  - build
  - deploy

variables:
  SERVICE_NAME: ngoni-ia-service-rasa
  REGISTRY: registry.gitlab.com/ngoni_ci/microservices
  IMAGE_TAG: $CI_COMMIT_SHORT_SHA

test:rasa:
  stage: test
  image: rasa/rasa:3.6.20
  script:
    - rasa data validate
    - rasa train
    - rasa test nlu --out results
    - rasa test
  artifacts:
    paths: [results/]
  rules:
    - if: '$CI_COMMIT_BRANCH == "main" || $CI_COMMIT_BRANCH == "develop"'

build:docker:
  stage: build
  image: docker:24
  services: [docker:24-dind]
  script:
    - docker build -t $REGISTRY/$SERVICE_NAME-rasa:$IMAGE_TAG ./rasa
    - docker build -t $REGISTRY/$SERVICE_NAME-actions:$IMAGE_TAG ./rasa/actions
    - docker push $REGISTRY/$SERVICE_NAME-rasa:$IMAGE_TAG
    - docker push $REGISTRY/$SERVICE_NAME-actions:$IMAGE_TAG
  rules:
    - if: $CI_COMMIT_TAG

deploy:staging:
  stage: deploy
  image: alpine:3.19
  script:
    - ssh $VPS_STAGING_USER@$VPS_STAGING_HOST "bash /opt/ngoni-gitops/scripts/deploy.sh $SERVICE_NAME $IMAGE_TAG"
  rules:
    - if: $CI_COMMIT_BRANCH
  needs: [build:docker]
```

Points volontairement absents de cette proposition (cohérent avec le
périmètre du chapitre) : tout job de type "LLM" (appel à une API de
génération, évaluation par LLM-judge, etc.) — aucun n'existe dans ce projet
à ce jour, et [16.5](16-audit-faq-nlu-2026-07.md) ne recommande d'explorer un
LLM qu'en re-ranking/désambiguïsation, comme piste future distincte du flow
Rasa lui-même, pas comme prérequis de son déploiement.

## 17.6 Limitations actuelles côté DevOps (flow Rasa)

| Limitation | Détail |
|---|---|
| Pas de CI/CD | Voir [17.5](#175-cicd--état-actuel-et-pipeline-proposé) |
| Secrets en clair | `rasa/.env`, `rasa/actions/.env` non chiffrés, sans rotation — voir [13.3](13-limitations.md#133-secrets-en-clair-dans-les-variables-denvironnement) |
| Mono-instance | Pas de réplication du conteneur `rasa` ni de l'action server — voir [13.7](13-limitations.md#137-pas-de-haute-disponibilité-ni-de-montée-en-charge-testée) |
| Mono-langue | Pipeline NLU entraîné et calibré exclusivement en français — un changement de langue nécessiterait un nouveau cycle complet d'entraînement/évaluation, pas une simple bascule de configuration — voir [13.5](13-limitations.md#135-portée-mono-langue) |

---
