← [Sommaire](README.md) | [10. Déploiement](10-deploiement.md)

# 11. Maintenance

## 11.1 Bonnes pratiques générales du dépôt

- **Commentaires orientés "pourquoi", pas "quoi"** : la convention observée
  dans tout le code de ce projet est de ne commenter que ce qui n'est pas
  évident à la lecture (un choix de seuil, un bug contourné, une contrainte
  externe) — jamais une paraphrase du code. À respecter en continuant le
  projet.
- **Justification empirique des seuils** : tout seuil de classification
  (similarité, marge relative...) est accompagné, dans le code, d'une mesure
  chiffrée qui l'a produit (voir [7.5](07-integration-ia.md#choix-du-modèle--historique-et-calibration-empirique)).
  Modifier un seuil sans mesure équivalente casse cette traçabilité.
- **Le contrat fait foi** : toute évolution du format d'échange
  Diagnostic Engine ↔ microservices doit d'abord passer par
  `contracts/diagnostic/v1/*.schema.json`, puis par le miroir Pydantic
  (`contracts.py`), jamais l'inverse (voir §7 de
  [`contracts/diagnostic/README.md`](../contracts/diagnostic/README.md)).

## 11.2 Ajouter une intention ou une action Rasa

1. Ajouter des exemples dans `rasa/data/nlu.yml` (nouvelle intention ou
   enrichissement d'une existante).
2. Déclarer l'intention dans `domain.yml` (`intents:`).
3. Décrire le parcours dans `rasa/data/stories.yml` et/ou `rules.yml`.
4. Si une action personnalisée est nécessaire, l'ajouter dans le fichier
   `rasa/actions/*.py` du domaine concerné (voir
   [3.2.1](03-taxonomie.md#321-rasaactions--serveur-dactions)) et la
   déclarer dans `domain.yml` (`actions:`).
5. Réentraîner (`rasa train`) et évaluer (`rasa test nlu`) avant de
   redéployer — voir [7.8](07-integration-ia.md#78-déploiement-dun-nouveau-modèle-rasa-en-production).

## 11.3 Ajouter un nouveau domaine FastAPI

Suivre le patron des domaines existants (`app/domains/{faq,complaints,feedback}`) :
`models.py` (ORM SQLAlchemy) → `repository.py` (accès données) →
`service.py` (logique métier) → `schemas.py` (Pydantic) → `router.py`
(endpoints), puis monter le router dans `app/main.py`
(`app.include_router(...)`). Le domaine `diagnostic` s'écarte de ce patron
strict en raison de sa complexité propre (voir
[3.4](03-taxonomie.md#34-fastapiappdomainsdiagnostic-en-détail)) — ne pas le
prendre comme modèle pour un domaine plus simple.

## 11.4 Rendre un nouveau microservice diagnosticable

1. Implémenter le contrat décrit dans
   [`contracts/diagnostic/README.md`](../contracts/diagnostic/README.md) :
   `GET /diagnostic/manifest` + un `POST /diagnostic/{problem_id}` par
   problème déclaré.
2. Valider chaque réponse contre les schémas de `contracts/diagnostic/v1/`
   (exemples fournis dans `v1/examples/`).
3. Ajouter une entrée dans `fastapi/services_registry.yaml` (voir
   [9.3](09-configuration.md#93-services_registryyaml--ajouter-un-microservice-diagnosticable)) —
   aucune modification de code côté moteur n'est nécessaire.
4. Le service devient diagnosticable au prochain cycle de rafraîchissement
   du Capability Registry (jusqu'à `REGISTRY_POLL_INTERVAL_SECONDS`), sans
   redémarrage.
5. Vérifier la classification avec `POST /diagnostic/debug/classify` (voir
   [6.2](06-api-reference.md#62-fastapi--diagnostic-diagnostic)) avant de
   considérer le problème correctement intégré — un nouveau problème peut
   entrer en collision sémantique avec un problème existant (voir les
   nombreux exemples de recalibrage documentés dans
   `wallet_service`/`user_service` `diagnostic/manifest.py`).

## 11.5 Mettre à jour un modèle IA

Voir [7.6 Remplacer le modèle d'embeddings](07-integration-ia.md#76-remplacer-le-modèle-dembeddings)
et [7.8 Déploiement d'un nouveau modèle Rasa](07-integration-ia.md#78-déploiement-dun-nouveau-modèle-rasa-en-production).

## 11.6 Migrations de schéma BD

Les scripts de `fastapi/migrations/` sont **incrémentaux et non
automatisés** — aucun outil de migration (Alembic...) n'est en place à ce
stade. Appliquer manuellement, dans l'ordre numérique, contre la base
`chatbotdb` :

```powershell
psql -U chatbot_user -d chatbotdb -f fastapi\migrations\0001_e5_base_upgrade.sql
psql -U chatbot_user -d chatbotdb -f fastapi\migrations\0002_feedback_table.sql
# ... etc., dans l'ordre
```

Toute nouvelle migration doit suivre la même convention de nommage
(`NNNN_description.sql`) et rester idempotente si possible (`IF NOT EXISTS`).

## 11.7 Résolution des problèmes courants

| Symptôme | Cause probable | Solution |
|---|---|---|
| Une action Rasa qui appelle une nouvelle URL FastAPI échoue silencieusement ("service indisponible") en conteneur, alors que le moteur tourne | La variable `*_SERVICE_URL` correspondante n'a pas été ajoutée à `rasa/actions/.env` (le fallback par défaut pointe vers `http://fastapi:8000/...`, qui ne résout pas dans le conteneur puisque `fastapi` n'y tourne pas) | Ajouter la variable dans `rasa/actions/.env` **et** `.env.example`, avec `http://host.docker.internal:8000/...` |
| Une variable modifiée dans `rasa/actions/.env` ne semble jamais prise en compte | `docker compose restart actions` réutilise l'environnement déjà "cuit" dans le conteneur — il ne relit **pas** `env_file` | `docker compose up -d --force-recreate actions` |
| Un nouveau problème diagnosticable n'apparaît pas côté bot | Cache de 5 minutes côté action server (`CAPABILITIES_CACHE_TTL_SECONDS`), ou cycle de rafraîchissement du Registry pas encore passé (`REGISTRY_POLL_INTERVAL_SECONDS`) | Attendre le prochain cycle, ou redémarrer le moteur pour forcer un rechargement immédiat |
| Un problème diagnostiqué à tort à la place d'un autre | Collision sémantique entre deux manifestes (embeddings trop proches) | Utiliser `POST /diagnostic/debug/classify` pour comparer les scores, enrichir `example_phrases`/`keywords` du bon problème plutôt que d'abaisser un seuil global |
| Le bot répond `nlu_fallback` sur un message pourtant compréhensible | Aucun mot du message n'est dans le vocabulaire d'entraînement (`vocabulary_guard`) | Ajouter des exemples couvrant ce vocabulaire dans `rasa/data/nlu.yml`, puis réentraîner |

## 11.8 Exécution de la suite de tests

```powershell
# Côté moteur FastAPI (pytest)
cd C:\DEV\PFE\fastapi
.venv\Scripts\python.exe -m pytest tests\

# Côté Rasa (NLU + parcours de dialogue)
docker compose exec rasa rasa test nlu --out results
docker compose exec rasa rasa test
```

Suite `fastapi/tests/` notable (tout le sous-système diagnostic y est
couvert en profondeur) : `test_diagnostic_pipeline.py`,
`test_diagnostic_registry_yaml.py`, `test_diagnostic_contract_conformance.py`,
`test_diagnostic_contracts.py`, `test_diagnostic_circuit_breaker.py`,
`test_diagnostic_adapter_resilience.py`, `test_diagnostic_audit_repository.py`,
`test_diagnostic_classification_quality.py`, `test_diagnostic_router.py`,
`test_ticket_creation.py`, `test_wallet_service.py`.

---

Suite : [12. Journalisation et supervision](12-logs-supervision.md)
