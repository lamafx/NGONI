← [Sommaire](README.md) | [6. Référence API](06-api-reference.md)

# 7. Intégration des modèles IA

## 7.1 Vue d'ensemble

Ce projet combine **deux briques IA distinctes**, qu'il ne faut pas confondre :

| | Modèle NLU Rasa | Modèle d'embeddings |
|---|---|---|
| Rôle | Comprendre l'intention et les entités d'un message | Mesurer la similarité sémantique entre deux textes |
| Technologie | `DIETClassifier` (Rasa), entraîné sur ce projet | `sentence-transformers`, modèle pré-entraîné réutilisé tel quel |
| Où il tourne | Conteneur `rasa` | Processus FastAPI (singleton partagé) |
| Utilisé par | Rasa Core directement | FAQ (`/faq/search`), Diagnostic (Capability Registry + classification côté action server) |
| Entraînement | Oui (`rasa train`, propre à ce projet) | Non — chargé pré-entraîné depuis Hugging Face |

## 7.2 Modèle NLU (DIETClassifier)

### Chargement

Le modèle est un artefact versionné produit par `rasa train`
(`rasa/models/<timestamp>-<nom>.tar.gz`). Rasa charge automatiquement le
modèle le plus récent du dossier `models/` au démarrage du conteneur `rasa`
(`GET /status` renvoie le fichier chargé).

### Pipeline (voir `rasa/config.yml`)

```
WhitespaceTokenizer
→ RegexFeaturizer
→ LexicalSyntacticFeaturizer
→ CountVectorsFeaturizer (mots entiers)
→ CountVectorsFeaturizer (char_wb, min_ngram=2, max_ngram=4)   # tolère fautes de frappe
→ DIETClassifier (80 epochs, 2 couches de transformer, taille 256)
→ EntitySynonymMapper
→ ResponseSelector
→ components.vocabulary_guard.VocabularyCoverageGuard          # composant personnalisé, voir 7.3
→ FallbackClassifier (threshold=0.6, ambiguity_threshold=0.1)
```

Le `CountVectorsFeaturizer` en `char_wb` (sous-chaînes de 2 à 4 caractères)
est ce qui permet de reconnaître "retra" comme proche de "retrait", ou "mon
compt es bloké" malgré les fautes — sans lui, seules les formes exactes
apprises en entraînement seraient reconnues.

Policies Core : `MemoizationPolicy`, `RulePolicy` (fallback natif),
`UnexpecTEDIntentPolicy`, `TEDPolicy`.

### 7.3 Le `vocabulary_guard` — garde-fou personnalisé

**Problème résolu** : avec `model_confidence: softmax`, le `DIETClassifier`
reste sur-confiant (~1.0) même sur du texte totalement hors-vocabulaire
(fautes de frappe sévères, texte aléatoire) — un `FallbackClassifier` seul
ne peut jamais intercepter une confiance de 1.0000. Bug constaté en
pratique : "fuck" classé avec confiance 1.0 dans une intention métier
existante au hasard.

**Fonctionnement** (`rasa/components/vocabulary_guard.py`) : composant NLU
personnalisé, inséré juste avant le `FallbackClassifier`. À l'entraînement,
il mémorise l'ensemble des mots (normalisés — accents supprimés, ≥ 3
lettres) apparaissant dans les exemples d'entraînement, toutes intentions
confondues. À l'inférence, si **aucun** mot du message n'est reconnu dans ce
vocabulaire, il force la confiance de l'intention déjà prédite à `0.0` — ce
qui déclenche naturellement le mécanisme de fallback déjà câblé
(`core_fallback_action_name: action_default_fallback`), sans code
supplémentaire côté Core.

Ne s'applique jamais aux messages sans aucun token alphabétique de 3+
lettres (une référence structurée comme `TOPUP-XYZ-123` ou un simple montant
n'a par nature aucun mot du langage courant à reconnaître) — ces cas sont
traités indépendamment de l'intention par capture verbatim
(`rasa/actions/diagnostic.py`).

### 7.4 Ré-entraînement et évaluation

```powershell
docker compose run --rm rasa train
docker compose exec rasa rasa test nlu --out results
```

`rasa test nlu` compare les prédictions du modèle aux exemples de
`rasa/tests/test_nlu.yml` et produit `results/` (matrice de confusion,
histogramme, rapport JSON par intention). `rasa test` (parcours complets)
s'appuie sur `rasa/tests/test_stories.yml`. Voir aussi
[11. Maintenance §11.8](11-maintenance.md#118-exécution-de-la-suite-de-tests).

## 7.5 Modèle d'embeddings (`intfloat/multilingual-e5-base`)

### Chargement

Singleton chargé une seule fois par process FastAPI
(`app/shared/embeddings/service.py::get_embedding_model`), réutilisé par
tous les domaines qui ont besoin de similarité sémantique (FAQ, Capability
Registry) — évite de dupliquer un modèle de plusieurs centaines de Mo dans
chaque conteneur qui en aurait besoin. Préchargé explicitement au démarrage
de `app.main` (`startup()`), plutôt que paresseusement au premier appel, pour
éviter qu'une première requête utilisateur post-redémarrage ne subisse le
coût de chargement (~10-20 s) dans le budget de timeout de 10 s alloué côté
Rasa.

### Appel

Convention E5 : préfixer différemment une **requête** (`"query: " + texte`)
et un **document/passage** comparé (`"passage: " + texte`) — nécessaire pour
la qualité de la similarité avec cette famille de modèles.

| Fonction | Usage |
|---|---|
| `embed_query(text)` | Un message utilisateur à comparer à des passages déjà indexés |
| `embed_query_batch(texts)` | Idem, en lot (ex. plusieurs segments d'un même message) |
| `embed_passage(text)` | Un contenu de référence à indexer (question FAQ, description de problème) |
| `embed_passage_batch(texts)` | Idem, en lot (ex. tout le catalogue de diagnostic en un seul appel modèle) |
| `cosine_similarity(a, b)` | Simple produit scalaire — les vecteurs sont déjà normalisés (`normalize_embeddings=True`) |

Exposé au reste de la plateforme (y compris l'action server Rasa, qui ne
charge jamais son propre modèle) via `POST /embeddings/query[/batch]` — voir
[6.5](06-api-reference.md#65-fastapi--embeddings-embeddings).

### Choix du modèle : historique et calibration empirique

Le modèle a été changé de `e5-small` vers `e5-base` (2026-07) suite à une
mesure sur le catalogue réel (8 problèmes wallet+user, 20 phrases
hors-sujet, 59 paraphrases en leave-one-out) : `e5-small` produisait un taux
de **faux positifs de 65 %** au seuil de classification diagnostic — une
simple salutation ("Bonsoir, comment allez-vous ?") pouvait déclencher un
diagnostic au hasard. `e5-base` (même famille, juste plus de paramètres)
descend ce taux à 10 % **et** améliore le rappel (66 % → 76 %) au même
seuil — gain net, pas un compromis.

Conséquence directe : la dimension des vecteurs passe de 384 à 768 — les
vecteurs déjà stockés en base **ne sont pas réutilisables tels quels**
(`core.faq_items.embedding`). Deux vecteurs ne sont comparables que s'ils
proviennent du même modèle.

Seuils calibrés pour ce modèle (à recalibrer si le modèle change à nouveau) :

| Constante | Valeur | Fichier | Rôle |
|---|---|---|---|
| `DEFAULT_THRESHOLD` | `0.85` | `app/domains/faq/service.py` | Seuil de correspondance FAQ |
| `MIN_EMBEDDING_SIMILARITY` | `0.84` | `rasa/actions/diagnostic.py` | Seuil de verrouillage d'un problème diagnostiqué |
| `KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY` | `0.78` | `rasa/actions/diagnostic.py` | Second plancher, uniquement pour le repêchage par mot-clé unique |

## 7.6 Remplacer le modèle d'embeddings

1. Changer `MODEL_NAME` dans `app/shared/embeddings/service.py`.
2. Recalculer **tous** les vecteurs déjà stockés — aucun mélange possible
   entre vecteurs de modèles différents :
   ```powershell
   cd fastapi
   .venv\Scripts\python.exe scripts\reembed_faq.py
   ```
   (Le Capability Registry, lui, n'a rien à ré-embedder manuellement : ses
   embeddings sont recalculés en mémoire à chaque `refresh()`, jamais
   persistés en base.)
3. Recalibrer empiriquement les seuils du tableau ci-dessus sur un corpus de
   test réel (positifs/négatifs) — un nouveau modèle ne garantit pas la même
   échelle de similarité que l'ancien (voir la migration e5-small → e5-base
   ci-dessus pour la méthode).
4. Si la dimension du vecteur change, prévoir la migration de colonne
   correspondante (voir `fastapi/migrations/0001_e5_base_upgrade.sql` comme
   référence).

## 7.7 Ajouter un nouveau modèle IA au système

Il n'existe pas de registre de modèles générique dans ce projet — chaque
brique IA est câblée explicitement. Pour en ajouter une nouvelle :

1. **Où l'enregistrer** : suivre le patron `app/shared/<nom>/service.py`
   (singleton chargé au démarrage, voir `embeddings/service.py`) si le
   modèle doit être partagé entre plusieurs domaines ; sinon dans le domaine
   qui l'utilise seul.
2. **Où câbler le chargement** : ajouter le préchargement dans
   `app/main.py::startup()` si le coût de chargement est significatif
   (même raisonnement que le modèle d'embeddings).
3. **Conventions de nommage** : nom de constante `MODEL_NAME` en tête de
   fichier, avec un commentaire justifiant le choix (voir l'exemple
   `embeddings/service.py`) — la justification empirique fait partie du
   contrat de maintenance de ce projet, pas une option.
4. **Exposition** : si d'autres processus (action server Rasa) doivent
   l'utiliser, l'exposer via un endpoint FastAPI dédié plutôt que de
   dupliquer le modèle dans un autre process (voir `/embeddings/query`
   comme référence).

## 7.8 Déploiement d'un nouveau modèle Rasa en production

1. Entraîner : `docker compose run --rm rasa train` (produit un nouveau
   `.tar.gz` dans `rasa/models/`).
2. Évaluer : `docker compose exec rasa rasa test nlu --out results` — comparer
   aux métriques du modèle précédent (rapport JSON par intention), ne jamais
   déployer une régression silencieuse.
3. Rasa charge automatiquement le modèle le plus récent au redémarrage du
   conteneur — un simple `docker compose restart rasa` suffit une fois le
   nouveau `.tar.gz` en place.
4. Conserver l'ancien `.tar.gz` (rollback immédiat possible en cas de
   régression constatée en usage réel).

---

Suite : [8. Pipeline de traitement](08-pipeline-traitement.md)
