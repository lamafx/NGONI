# ngoni-ia-service — Note technique (mise à jour)

Nettoyage du dépôt, optimisation des images Docker et points ouverts pour le
déploiement — préparé pour l'équipe DevOps · **2026-07-22** (mise à jour de
la note du 2026-07-19, mêmes tests rejoués sur l'état actuel du dépôt,
branche `opt-ia`)

## 0. Résumé des écarts par rapport à la note du 2026-07-19

| # | Point de la note initiale | État aujourd'hui |
|---|---|---|
| 2 | Nettoyage du dépôt | ✅ Toujours valide, mais ⚠️ `.git` local à 912 Mo (résidu non purgé, voir §1) |
| 5 | Modèle Rasa livré via build multi-étapes | ❌ **Régression** — le Dockerfile est repassé en single-stage, le modèle n'est plus intégré à l'image (voir §3) |
| 6 | Tailles d'image (363 Mo / 1119 Mo) | ❌ Non reproductibles — mesures actuelles très supérieures, cause identifiée en partie (voir §4) |
| — | Build de l'image `rasa` | 🔴 **Était cassé** avant intervention aujourd'hui (contexte Docker invalide) — corrigé (voir §2) |
| 4, 7 | Base de données partagée, CI/CD | ⏸️ Toujours "à faire", inchangé (voir §5, §6) |

## 1. Nettoyage du dépôt — toujours valide, une anomalie locale trouvée

Le nettoyage décrit dans la note initiale (exclusion de `rasa/.rasa/` et
`rasa/models/`, correctif `.env.*`/`!.env.example`, retrait de
`rasa/.config/rasa/global.yml` et `rasa/.keras/keras.json`) est **toujours
en place** et vérifié :

- `.gitignore` contient bien toutes les règles décrites.
- Aucun fichier sous `rasa/.rasa/`, `rasa/models/`, `rasa/.config/`,
  `rasa/.keras/` n'est suivi (`git ls-files` vide sur ces préfixes).
- 171 fichiers suivis au total.
- Aucun blob issu de l'ancien `rasa/.rasa/cache/` n'existe dans l'historique
  atteignable (`git rev-list --objects --all` ne remonte aucun objet sous ce
  chemin) — la purge de l'historique a bien fonctionné, pas seulement le
  `.gitignore` en avant.

**Anomalie trouvée, locale uniquement :** le dossier `.git` de cette copie
de travail pèse **912 Mo**, pas ~868 Ko. Cause : 927 objets `blob`/`tree`
**non empaquetés et non atteignables** (confirmé via `git fsck
--unreachable` — 634 objets `unreachable`, dont plusieurs blobs de
40 à 54 Mo), résidus de l'opération de réécriture d'historique elle-même,
jamais garbage-collectés localement (`git count-objects -v` : 927 loose,
0 pack). Ça n'affecte ni le dépôt distant ni un clone frais depuis GitLab
(ces objets ne sont reliés à aucune branche) — uniquement le poids sur
disque de cette copie locale. Correctif possible : `git gc` (non exécuté
ici, en dehors du périmètre demandé, à valider avec la personne qui a fait
le nettoyage avant de purger des objets).

## 2. Bug bloquant trouvé et corrigé : build `rasa` cassé

En relançant `docker compose build`, le build de l'image `rasa` **échouait
systématiquement** :

```
#19 ERROR: invalid file request .cache/huggingface/hub/models--camembert-base/snapshots/.../config.json
target rasa: failed to solve: invalid file request ...
```

**Cause :** `rasa/.dockerignore` n'excluait pas `.cache/` — le contexte
Docker embarquait donc `rasa/.cache/huggingface/` (cache HuggingFace local
de l'expérimentation CamemBERT, **519 Mo**, structure standard avec
symlinks `snapshots/ → blobs/`). BuildKit refuse de transférer un des
fichiers de ce cache (symlink que son mécanisme de sync de contexte ne sait
pas traiter). Le transfert de contexte à lui seul montait déjà à 543 Mo
avant l'échec.

Ce dossier est déjà exclu de **git** (`.gitignore` contient `*.cache`, qui
matche `rasa/.cache`) mais ne l'était pas de **Docker** — deux mécanismes
d'exclusion distincts, l'oubli portait uniquement sur le second.

**Corrigé** : ajout de `.cache/` à `rasa/.dockerignore`. Après correction,
les trois images (`fastapi`, `rasa`, `actions`) se construisent sans erreur.
Ce correctif est appliqué dans la copie de travail (non commité) — à
committer avec le reste des ajustements DevOps.

> Tant que ce correctif n'est pas commité, **tout build `rasa` échoue** dès
> qu'un cache HuggingFace existe localement dans `rasa/.cache/` — c'est le
> cas dès qu'on a lancé une fois l'expérimentation
> `config-embedding-experiment.yml`. Point à committer en priorité, avant
> même la mise en place de la CI (un job de build sur GitLab échouerait de
> la même façon si ce dossier existait dans le contexte transmis).

## 3. Modèle Rasa entraîné : régression du build multi-étapes

La note initiale décrivait une solution "retenue et déjà implémentée" : le
`Dockerfile` de `rasa` entraînait le modèle *pendant* le build, en deux
étapes (`trainer` jetable → `COPY --from=trainer /app/models /app/models`).
Vérification faite aujourd'hui :

- Au commit `60a064d` (celui de la note), le Dockerfile était bien
  multi-étapes, avec le `RUN rasa train` dans l'étape `trainer`.
- Le commit suivant, `a4513e2` ("Add evaluation results and visualizations
  for DIETClassifier", 2026-07-21), **a remplacé ce Dockerfile par une
  version single-stage**, sans entraînement ni `COPY --from=trainer`.
- Confirmé en construisant l'image aujourd'hui : `/app/models/` **n'existe
  pas** dans l'image `pfe-rasa:latest` construite depuis l'état actuel du
  dépôt.

**Conséquence concrète** : dans l'état actuel du code, une image `rasa`
construite sur un serveur distant démarrerait **sans aucun modèle chargé**
— `rasa/models/` est gitignorée (à raison) et il n'existe plus de mécanisme
pour l'y faire apparaître à la construction. Le problème que la note de
juillet résolvait explicitement ("le modèle ne peut être ni commité ni
transporté par bind-mount vers un serveur distant") **est revenu**.

**À faire avant tout déploiement distant** : réappliquer le build
multi-étapes (le diff est disponible à `60a064d` pour `rasa/Dockerfile`,
à fusionner avec l'ajout `transformers`/`sentencepiece` introduit depuis
pour `config-embedding-experiment.yml`). Point d'attention already noté
dans la version précédente de cette note, toujours valable : l'entraînement
réel prend ~2h11 sur la machine de test — le job CI correspondant doit
rester `when: manual`, scopé à `rules: changes: [rasa/**]`.

## 4. Optimisation des images — nouvelles mesures (2026-07-22)

Les trois images ont été reconstruites intégralement depuis l'état actuel
du code (`docker compose build fastapi rasa actions`, après correction du
`.dockerignore` ci-dessus) :

| Image | Taille mesurée aujourd'hui | Taille annoncée (note du 19/07) | Écart |
|---|---|---|---|
| `fastapi` | **1,81 Go** | 363 Mo | Non reproduit — voir explication ci-dessous |
| `rasa` | **4,43 Go** | 1119 Mo (avec modèle) | Non reproduit — voir explication ci-dessous |
| `actions` | **349 Mo** | ~76 Mo (implicite dans le total) | Non reproduit, cause non investiguée |
| **Total** | **≈ 6,59 Go** | ≈ 1,56 Go | — |

**`fastapi` — l'optimisation torch CPU-only fonctionne toujours**, vérifié
en conteneur : `torch 2.5.1+cpu`, `torch.cuda.is_available() == False`,
aucun paquet `nvidia-*`. `requirements.txt` est identique (`git diff
60a064d HEAD -- fastapi/requirements.txt` ne montre rien) et le contexte de
build ne pèse que 633 Ko (pas de fuite de type `.venv` copié par erreur).
Le poids vient du contenu réel des paquets installés — `torch` seul pèse
684 Mo décompressé dans l'image, `scipy` 109 Mo, `transformers` 81 Mo,
`sympy` 56 Mo, `scikit-learn` 46 Mo, `numpy` 41 Mo (dépendances
transitives de `sentence-transformers`, elles-mêmes non figées par version
dans `requirements.txt` : seul `sentence-transformers==3.0.1` est pinné,
pas `torch`/`transformers`/`scipy`/`scikit-learn`). Le chiffre de 363 Mo de
la note initiale n'est pas reproductible avec cette liste de dépendances —
soit il correspondait à une mesure partielle (une seule couche, pas
l'image complète), soit les versions résolues par pip ont changé depuis.
**Recommandation** : figer les versions transitives critiques (`torch`,
`transformers`) dans `requirements.txt` pour que la taille de l'image soit
reproductible, et mesurer avec `docker image inspect --format='{{.Size}}'`
plutôt qu'à l'œil pour les prochains rapports.

**`rasa` — le poids vient très majoritairement de l'image de base**, pas de
ce projet : `rasa/rasa:3.6.20` pèse à lui seul **4,3 Go** (vérifié par
`docker pull rasa/rasa:3.6.20` puis `docker images`), avant même la moindre
ligne du `Dockerfile` de ce dépôt (qui n'ajoute que ~101 Mo :
`transformers`/`sentencepiece` + le code). Les chiffres de la note initiale
(1071 Mo avant / 1119 Mo après) sont **incompatibles avec la taille de
l'image de base elle-même** — il n'existe pas de configuration de ce
Dockerfile qui produirait une image finale plus petite que son `FROM`. Ces
chiffres doivent être considérés comme erronés ou mesurant autre chose que
la taille totale de l'image (peut-être la taille ajoutée par l'étape
`trainer` seule) ; à ne pas réutiliser tels quels dans une communication
externe sans nouvelle vérification.

**`actions`** : 349 Mo, cohérent avec une image `rasa-sdk` + deux
dépendances Python (`rasa-sdk==3.6.2`, `requests`) — pas d'optimisation
tentée sur ce Dockerfile jusqu'ici (jamais modifié depuis le commit initial
`86189b0`), donc pas de régression, simplement une taille jamais mesurée
précisément dans la note d'origine.

## 5. Base de données : statut inchangé

Toujours **non fait** : `.env` local pointe encore sur une base dédiée
(`chatbotdb` / `chatbot_user`), pas sur la base `ngoni` partagée décrite
dans la note. `fastapi/init_db.sql` confirme toujours l'usage de
`vector(768)` pour les colonnes d'embeddings (cohérent avec la demande de
confirmation `pgvector` à formuler). **Non vérifiable depuis cet
environnement** : le dépôt `ngoni-core-service` (source de la référence à
`docs/ARCHITECTURE.md`) n'est pas présent ici — à revérifier directement
avec l'équipe core ou dans son propre dépôt.

## 6. Ce qu'il reste à faire côté DevOps (mise à jour)

| Action | Statut |
|---|---|
| Corriger `rasa/.dockerignore` (cache HuggingFace bloquant le build) | ✅ **fait aujourd'hui** — à committer |
| Réintégrer le build multi-étapes du modèle Rasa (régression §3) | 🔴 **à refaire** (perdu depuis `a4513e2`) |
| Créer `.gitlab-ci.yml` (stages `test → security → build → deploy`) | à faire (toujours) |
| Job `build:docker:rasa` en `when: manual` + `rules: changes: [rasa/**]` | à faire (toujours) |
| Figer les versions transitives lourdes (`torch`, `transformers`) dans `fastapi/requirements.txt` pour des tailles reproductibles | à faire (nouveau, voir §4) |
| Provisionner schéma + identifiants + pgvector sur la base `ngoni` partagée | à faire (toujours) |
| Variables CI/CD (`WALLET_SERVICE_*`, `USER_SERVICE_*`, `DATABASE_URL`, `RASA_PARSE_URL`, `RASA_WEBHOOK_URL`) | à faire (toujours) |
| Étape de déploiement (SSH + script central), sur le modèle des 2 autres services | à faire (toujours) |
| `git gc` local (912 Mo d'objets orphelins, §1) | à faire (optionnel, cosmétique local) |
| Nettoyage du dépôt (cache, modèles, config machine-locale) | fait (toujours valide) |

---

Branche : `opt-ia` · Dépôt : `gitlab.com/ngoni_ci/microservices/ngoni-ia-service`
· Commits de référence : nettoyage `86189b0`/`813b2ff`, optimisation images
`60a064d`, régression Dockerfile `a4513e2` · Tests rejoués et mesures
prises le 2026-07-22.
