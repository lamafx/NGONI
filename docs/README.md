# Documentation — ngoni-ia-service

Assistant conversationnel NGONI (Rasa + moteur FastAPI) : FAQ sémantique, diagnostic métier, réclamations et feedback.

## Sommaire

| # | Document | Contenu |
|---|----------|---------|
| 1 | [Présentation générale](01-presentation.md) | Contexte, objectifs, cas d'usage, glossaire |
| 2 | [Architecture globale](02-architecture.md) | Composants, Capability Registry, choix techno |
| 3 | [Taxonomie du projet](03-taxonomie.md) | Organisation des dossiers (`rasa/`, `fastapi/`, contrats) |
| 4 | [Architecture des services](04-services.md) | Rasa, Action Server, domaines FastAPI, stubs |
| 5 | [Communication](05-communication.md) | Protocoles HTTP, séquences FAQ / diagnostic |
| 6 | [Référence API](06-api-reference.md) | Endpoints FastAPI, Rasa, stubs, contrat diagnostic |
| 7 | [Intégration IA](07-integration-ia.md) | DIETClassifier, embeddings e5-base, vocabulary guard |
| 8 | [Pipeline de traitement](08-pipeline-traitement.md) | Parcours message → réponse |
| 9 | [Configuration](09-configuration.md) | Variables d'environnement, `services_registry.yaml` |
| 10 | [Déploiement](10-deploiement.md) | Installation locale, ordre de démarrage |
| 11 | [Maintenance](11-maintenance.md) | Migrations, entraînement, tests |
| 12 | [Logs & supervision](12-logs-supervision.md) | Observabilité |
| 13 | [Limitations](13-limitations.md) | Contraintes actuelles (sécurité, prod) |
| 14 | [Évolutions](14-evolutions.md) | Roadmap |
| 15 | [Modèle de données](15-modele-donnees.md) | Schémas PostgreSQL |

## Workflows inter-services

Voir [WORKFLOW.md](WORKFLOW.md) pour les flux opérationnels (FAQ, diagnostic, escalade, feedback) et les appels vers `wallet-service` / `user-service`.

## README service

Vue d'ensemble rapide (stack, ports, endpoints, lancement) : [../README.md](../README.md).
