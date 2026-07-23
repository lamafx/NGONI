← [Sommaire](README.md) | [19. Audit adversarial complémentaire](19-audit-adversarial-2026-07-23.md)

# 20. Réentraînement v7, abandon de CamemBERT et automatisation de l'urgence (2026-07-23)

Suite directe de [19.5](19-audit-adversarial-2026-07-23.md#195-décision-requise) et
[19.6](19-audit-adversarial-2026-07-23.md#196-actions-déjà-appliquées-dans-cette-session) :
les deux décisions P0 laissées ouvertes par le chapitre 19 (sort de
CamemBERT, réentraînement des correctifs déjà écrits dans `nlu.yml`/
`rules.yml`/`domain.yml`) ont été tranchées et exécutées dans cette session.

## 20.1 Décision — abandon formel de CamemBERT

**Décision du mainteneur** : abandon, sans ambiguïté. Les chiffres qui la
motivent, déjà mesurés en [16.8](16-audit-faq-nlu-2026-07.md#168-post-scriptum--tentatives-de-correctif-expérimentées-le-soir-même) :

| Mesure | Valeur |
|---|---|
| Gain d'accuracy globale (corpus adversarial 435 msg) | +1,2 pt (65,4 % → 66,6 %) |
| Gain sur le sous-ensemble `ask_faq`/`diagnostic` | +0,9 pt (71,1 % → 72,0 %) |
| Coût de latence `/model/parse` | ~15-20× (0,05-0,07 s → ~0,95 s) |
| Déséquilibre `diagnostic`/`ask_faq` (387 vs 210 exemples) | non traité par ce changement |
| Industrialisation | dépendances figées dans `rasa/Dockerfile` mais jamais mesurées bout-en-bout |

Gain jugé réel mais insuffisant face au coût pour un assistant conversationnel
temps réel. **Actions appliquées** : `rasa/Dockerfile` nettoyé (retrait de
`transformers==4.26.0`/`sentencepiece`, jamais utilisés par le pipeline
réellement servi — `config.yml` ne référence aucun `LanguageModelFeaturizer`).
`config-embedding-experiment.yml` et les modèles associés
(`rasa/models/experiments/faq-diagnostic-embedding-v1.tar.gz`,
`v2-replace.tar.gz`) conservés pour référence, non supprimés.

## 20.2 Automatisation du niveau d'urgence (réclamation)

Décision complémentaire prise avant le réentraînement : le formulaire
`reclamation_form` demandait jusqu'ici explicitement le niveau d'urgence
(`utter_ask_urgency` : *"Quel est le niveau d'urgence ? (faible, moyenne,
élevée)"*) — jugé peu pertinent pour l'utilisateur (ce jugement doit se
déduire de ce qu'il décrit, pas lui être délégué).

**Modifications** (`rasa/domain.yml`, `rasa/actions/reclamation.py`) :

- `urgency` retiré de `reclamation_form.required_slots` ; son mapping passe
  de `from_text` (conditionné au formulaire) à `type: custom` — ne peut plus
  être rempli que par une action, jamais par une réponse directe.
- `utter_ask_urgency`/`utter_wrong_urgency` supprimés ; `validate_urgency`
  (validation de la réponse texte) supprimé, devenu mort.
- Nouvelle fonction `_infer_urgency_from_description()` (`reclamation.py`),
  appelée systématiquement dans `validate_description` — même principe que
  `_infer_category_from_description`, déjà en place pour la catégorie.
  Signaux : mots-clés d'urgence explicite ("urgent", "bloqué", "piraté",
  "volé", "suspendu"...), et détection "depuis X jours/semaines/mois" (un
  problème qui traîne depuis plusieurs jours ou plus est traité comme urgent
  même sans mot d'urgence explicite). Repli neutre : `medium` (déjà le
  comportement par défaut existant partout ailleurs dans le code).
- Option "urgence" retirée du menu "modifier un champ" (`field_to_edit`) —
  cohérent avec le principe : ce champ n'est plus éditable manuellement du
  tout, il est entièrement recalculé à chaque description.
- `rasa data validate` : aucune erreur, aucun conflit de stories après ces
  changements.

## 20.3 Réentraînement v7 — résultats

`rasa train --fixed-model-name retrained-audit-fixes-v7`, avec l'ensemble des
changements ci-dessus plus ceux déjà présents dans le working tree avant
cette session (34 exemples `ask_complaint_status`, 3 règles `rules.yml`,
nettoyage de 11 slots dormants + entité `urgency`, voir
[19.6](19-audit-adversarial-2026-07-23.md#196-actions-déjà-appliquées-dans-cette-session)).
Remesuré avec `rasa test nlu --nlu tests/test_nlu_adversarial.yml` — **même
corpus de 90 exemples** que le modèle précédemment servi
(`test-audit-quick.tar.gz`, mesuré en 19.2), comparaison donc directement
valide (contrairement à la comparaison 16.1/19.2 sur deux corpus différents).

| Mesure | `test-audit-quick` (22/07) | `retrained-audit-fixes-v7` (23/07) | Écart |
|---|---:|---:|---:|
| **Accuracy globale (n=90)** | **75,6 %** | **71,1 %** | **-4,5 pt** |
| `ask_complaint_status` recall | 0 % | **100 %** | **+100 pt** |
| `ask_complaint_status` precision | 0 % | 100 % | +100 pt |
| `ask_faq` recall | 78,1 % | 59,4 % | -18,7 pt |
| `ask_faq` precision | 92,6 % | 76,0 % | -16,6 pt |
| `diagnostic` precision | 85,7 % | 52,0 % | -33,7 pt |
| `diagnostic` recall | 85,7 % | 92,9 % | +7,2 pt |
| `plainte` recall | 40 % | 20 % | -20 pt |
| `suggestion` recall | 80 % | 60 % | -20 pt |
| `bot_challenge` recall (n=2) | 100 % | 50 % | -50 pt |
| `create_reclamation` recall | 87,5 % | 81,25 % | -6,25 pt |
| `out_of_scope` precision | 53,8 % | 75,0 % | +21,2 pt |
| `greet` recall | 66,7 % | 100 % | +33,3 pt |

Détail des nouvelles erreurs `ask_faq` → `diagnostic` (9 des 32 exemples
`ask_faq`, confiance 1.0 pour la quasi-totalité) — même famille que
[16.4](16-audit-faq-nlu-2026-07.md#164-échecs-représentatifs-extraits-texte-exact-envoyé)/[19.3](19-audit-adversarial-2026-07-23.md#193-constat-1--la-collision-ask_faqdiagnostic-p0-est-toujours-active),
plus étendue :

> "Comment récupérer l'accès à mon compte si j'ai oublié mon mot de passe ?",
> "Quelle est la démarche pour changer de mot de passe ?", "Comment fonctionne
> la vérification du compte en général ?", "C'est quoi la procédure normale
> pour un retrait d'argent ?", "koman on peu changé le mdp de son compte",
> "jarive pa a me co koman on fé" → toutes classées `diagnostic`, confiance
> 1.0.

## 20.4 Analyse et décision

Troisième occurrence documentée du même phénomène que
[16.8](16-audit-faq-nlu-2026-07.md#168-post-scriptum--tentatives-de-correctif-expérimentées-le-soir-même)
(v1 : -2,4 pt ; v2 : -2,2 pt avec -20 pt collatéral sur `out_of_scope`) : sur
ce pipeline bag-of-words/char-n-gram à ~2000 exemples, modifier `nlu.yml`
pour cibler une intention précise déstabilise la frontière de décision
globalement, de façon non prédictible à l'avance. Cette fois, l'ajout de 34
exemples `ask_complaint_status` a résolu intégralement l'intention ciblée
mais a mesurablement aggravé la collision `ask_faq`/`diagnostic` (déjà le
problème P0 non résolu depuis le 16 juillet, rang 1 et 2 du classement des
compétences — [18.2](18-rapport-competences.md#182-vue-densemble)) : 9
exemples `ask_faq` de plus absorbés par `diagnostic` à confiance 1.0 dans ce
seul corpus de 90 messages, et `diagnostic` passe de 85,7 % à 52,0 % de
précision.

**Décision (mainteneur)** : rollback. Le gain (`ask_complaint_status`,
intention à faible volume dans un pilier qui disposait déjà d'un repli
partiel — les questions de statut mal classées tombaient sur
`create_reclamation`, pas dans le vide) ne compense pas la dégradation des
deux compétences les plus centrales et les plus lourdement investies du
projet. `retrained-audit-fixes-v7.tar.gz` déplacé vers
`rasa/models/experiments/` (même traitement que les tentatives v1/v2/
CamemBERT) ; `test-audit-quick.tar.gz` remis en service
(`docker restart pfe-rasa-1`, confirmé via `GET /status` :
`"model_file":"test-audit-quick.tar.gz"`). Les changements `nlu.yml`/
`rules.yml`/`domain.yml` restent dans le dépôt (non annulés) : base de
travail pour une future tentative qui traiterait le réentraînement
`ask_complaint_status` **en même temps** que le déséquilibre structurel
`diagnostic`/`ask_faq`, plutôt que successivement.

## 20.5 Enseignement pour la suite

Trois tentatives successives (v1, v2, v7), trois mécanismes de correctif
différents (nettoyage ciblé, enrichissement à grande échelle, nouvelle
intention), un seul dénominateur commun : **toute modification de `nlu.yml`
sur ce pipeline doit être remesurée intégralement sur le corpus adversarial
avant d'être déployée** — aucune ne peut être présumée sûre a priori, y
compris celles qui semblent strictement additives et ciblées sur une
intention sans lien apparent avec les autres. Le corpus
`tests/test_nlu_adversarial.yml` (90 exemples, indépendant) est ce qui a
permis de détecter cette régression avant déploiement réel ; sans lui, ce
changement serait passé pour une amélioration pure.

---

Suite : [21. Rapport de bouclage feedback](21-rapport-feedback.md)
