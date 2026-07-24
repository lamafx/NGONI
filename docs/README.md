# Documentation technique — Assistant conversationnel NGONI

Cette documentation couvre le **périmètre de l'assistant conversationnel** de
la plateforme NGONI : le bot Rasa, le moteur FastAPI (FAQ, diagnostic,
réclamations, feedback, embeddings), les stubs de microservices utilisés en
développement, et les contrats qui relient le moteur de diagnostic aux
microservices métier. Les autres domaines de la plateforme (vidéos,
paiements, modération, LCB-FT, gestion des comptes...) ne sont documentés ici
que dans la mesure où l'assistant les consomme — leur documentation propre
vit dans leurs dépôts respectifs (`ngoni-core-service/docs`,
`ngoni-admin-service/docs`, etc.).

Public visé : développeurs et mainteneurs amenés à comprendre, déployer,
faire évoluer ou dépanner ce périmètre.

## Sommaire

| # | Chapitre | Contenu |
|---|---|---|
| 1 | [Présentation générale](01-presentation.md) | Contexte, objectifs, cas d'usage, fonctionnalités, glossaire |
| 2 | [Architecture globale](02-architecture.md) | Vue d'ensemble, composants, choix technologiques |
| 3 | [Taxonomie du projet](03-taxonomie.md) | Arborescence commentée, rôle de chaque module |
| 4 | [Architecture des services](04-services.md) | Rasa, Actions, moteur FastAPI par domaine, stockage |
| 5 | [Communication entre services](05-communication.md) | Protocoles, flux de données, diagrammes de séquence |
| 6 | [Référence API](06-api-reference.md) | Endpoints détaillés (méthode, paramètres, réponses, erreurs) |
| 7 | [Intégration des modèles IA](07-integration-ia.md) | Modèle NLU Rasa, modèle d'embeddings, ajout/remplacement |
| 8 | [Pipeline de traitement](08-pipeline-traitement.md) | Parcours complet d'une requête utilisateur |
| 9 | [Configuration](09-configuration.md) | Variables d'environnement, fichiers de config, seuils |
| 10 | [Déploiement](10-deploiement.md) | Installation, ordre de démarrage, vérifications |
| 11 | [Maintenance](11-maintenance.md) | Bonnes pratiques, extensions courantes, dépannage |
| 12 | [Journalisation et supervision](12-logs-supervision.md) | Logs, traçabilité, gestion des erreurs |
| 13 | [Limitations actuelles](13-limitations.md) | Ce qui n'est délibérément pas fait à ce stade, et pourquoi |
| 14 | [Perspectives d'évolution](14-evolutions.md) | Pistes pour la suite du projet |
| 15 | [Modèle de données](15-modele-donnees.md) | Schémas PostgreSQL réels, pgvector, tables, conventions |
| 17 | [DevOps — flow Rasa](17-devops.md) | Build/train/test/deploy/rollback des conteneurs `rasa`/`actions`, CI/CD proposée, hors périmètre LLM |
| 18 | [Rapport des compétences](18-rapport-competences.md) | Classement des compétences de l'assistant, du plus important au plus mineur, et propositions priorisées |

## Statut de rédaction

- [x] Chapitres 1 à 15 rédigés
- [x] Chapitre 17 rédigé (DevOps — flow Rasa)
- [x] Chapitre 18 rédigé (Rapport des compétences)

## Conventions utilisées dans ce document

- Les schémas sont exprimés en [Mermaid](https://mermaid.js.org/), lisibles
  directement dans GitHub/GitLab et la plupart des visionneuses Markdown.
- Les extraits de commande sont donnés pour PowerShell (Windows), plateforme
  de développement de référence de ce projet.
- Un encadré **⚠️** signale un choix délibérément non sécurisé ou non
  finalisé pour l'environnement de développement actuel (voir chapitre 13
  pour la liste consolidée).
