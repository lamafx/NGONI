← [18. Le modèle d'embeddings partagé](18-modele-embeddings-partage.md) | [Index](00-index.md)

# 19. Vérifications effectuées et écarts trouvés

> **Rôle de ce document** : la méthode utilisée pour écrire ce rapport, et
> la liste consolidée des écarts trouvés entre le code actuel et la
> documentation existante — pour qu'un futur lecteur sache exactement quoi
> revérifier plutôt que de faire confiance aveuglément à l'un ou l'autre.

## Méthode

Ce rapport a été écrit le 2026-07-31 en lisant **directement le code
source actuel**, fichier par fichier — pas en résumant la documentation
existante (`../01-presentation.md` à `../18-rapport-competences.md`), pour
refléter l'état réel du projet plutôt que l'état documenté au moment de sa
rédaction. Fichiers lus intégralement ou en grande partie pour ce rapport :

- `fastapi/app/main.py`
- `fastapi/app/domains/diagnostic/{pipeline,registry,contracts,router,adapter,circuit_breaker,escalation}.py`
- `fastapi/app/domains/{complaints,feedback,audit}/service.py`
- `fastapi/app/domains/nlu/engines.py`
- `fastapi/app/shared/rasa_client.py`
- `rasa/domain.yml`, `rasa/config.yml`
- `rasa/actions/{diagnostic,common,reclamation,faq,feedback}.py` (intégralement ou en grande partie)
- `frontend/pages/chat/{chat.controller.js,chat.page.js}`
- `frontend/modules/admin/components/dashboard-shell.js`, `dashboard.controller.js`

Complété par une vérification **en conditions réelles** le même jour :
Postgres, Rasa, Actions, FastAPI et les services wallet/user tous démarrés
simultanément, captures d'écran du chat (sélecteur de modèle peuplé,
"Rasa (DIETClassifier)") et du dashboard admin (KPI avec données réelles :
"Réclamations ouvertes 199", "Satisfaction utilisateur 60 %") — voir
échange de conversation du 2026-07-31.

## Écarts trouvés

### `../08-pipeline-traitement.md` §8.4 — composant NLU obsolète

Ce chapitre mentionne un composant `VocabularyCoverageGuard` qui force la
confiance NLU à 0 si aucun mot du message n'est reconnu du vocabulaire
d'entraînement. **Ce composant n'apparaît plus dans `rasa/config.yml`
actuel** (voir [5. Le pipeline NLU de Rasa](05-rasa-nlu-pipeline.md) pour
le pipeline réellement actif). Cohérent avec `rasa/components/vocabulary_guard.py`
apparaissant comme suppression en cours (`git status`, non commitée) sur la
branche `opt-embedding` au moment de la rédaction.

**Action recommandée** : si cette suppression est confirmée définitive
(pas un simple travail en cours), corriger `../08-pipeline-traitement.md`
§8.4 pour retirer la mention de ce composant.

## Ce qui n'a PAS été revérifié en détail

Ce rapport se concentre sur le parcours **chat + diagnostic**, la partie la
plus élaborée du système. N'ont pas été relus en détail pour ce rapport
(la documentation existante reste la référence pour ces points) :

- Le détail complet de `rasa/actions/reclamation.py` (1335 lignes — seules
  les fonctions citées au [chapitre 9](09-action-reclamation-formulaire.md)
  ont été lues).
- Le modèle de données PostgreSQL complet (`../15-modele-donnees.md` reste
  la référence).
- Le flow DevOps de build/déploiement des conteneurs Rasa/Actions
  (`../17-devops.md` reste la référence).
- Les 5 classifieurs `nlu_bge` eux-mêmes (leur entraînement, pas leur
  utilisation en inférence — voir `rasa/nlu_bge/train.py`, hors périmètre
  de ce rapport).

## Comment garder ce rapport à jour

Ce rapport est un **instantané** du 2026-07-31, pas un document vivant
généré automatiquement. Si le code évolue significativement (en particulier
la branche `opt-embedding` mentionnée ci-dessus), les valeurs précises
citées ici (seuils, numéros de ligne implicites, noms de fichiers) peuvent
devenir obsolètes — revérifier contre le code avant de citer un détail
précis de ce rapport comme fait établi, plutôt que de lui faire confiance
indéfiniment.
