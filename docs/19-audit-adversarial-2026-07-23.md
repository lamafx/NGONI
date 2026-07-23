← [Sommaire](README.md) | [18. Rapport des compétences](18-rapport-competences.md)

# 19. Audit adversarial complémentaire (2026-07-23)

Suite directe de l'application des propositions du
[chapitre 18](18-rapport-competences.md#185-propositions) : exécution réelle,
contre l'instance Rasa locale (conteneur `pfe-rasa-1`, port 5005), d'un
nouveau corpus de non-régression adversarial
(`rasa/tests/test_nlu_adversarial.yml`, 90 exemples annotés), construit
indépendamment de `rasa/data/nlu.yml` et ciblant en priorité les deux zones
que le rapport de compétences classait comme les plus importantes et les
moins bien mesurées : la collision `ask_faq`/`diagnostic` (P0) et le pilier
Réclamation (P1, jamais couvert par [l'audit du 16 juillet](16-audit-faq-nlu-2026-07.md)).

**⚠️ Provenance du modèle testé.** Le modèle chargé au moment de ce test est
`models/test-audit-quick.tar.gz` (produit le 2026-07-22), **différent** de
`retrained-audit-fixes-v6.tar.gz` (2026-07-20) désigné comme "le modèle
réellement déployé" par les commentaires de `nlu.yml` au moment de la
rédaction du chapitre 16. Son origine exacte (expérimentation en cours,
issue possiblement du nettoyage `nlu.yml` du 2026-07-22 mentionné dans les
commentaires du fichier) n'a pas été investiguée ici — ce chapitre mesure
**le modèle actuellement servi**, pas nécessairement celui documenté comme
canonique. À vérifier avant toute décision basée sur ces chiffres.

## 19.1 Méthode

- Corpus : 90 messages annotés, répartis sur 10 intentions, construits selon
  la même méthode que [16.1](16-audit-faq-nlu-2026-07.md#161-résultats-chiffrés)
  (catégories A à I) sans reprendre le vocabulaire de `nlu.yml`.
- Exécution : `rasa test nlu --nlu tests/test_nlu_adversarial.yml --out
  results/adversarial`, à l'intérieur du conteneur `rasa` (accès direct au
  modèle chargé, pas d'appel HTTP intermédiaire).
- Sorties brutes : `rasa/results/adversarial/intent_report.json` (métriques
  par intention) et `intent_errors.json` (22 erreurs individuelles, texte +
  prédiction + confiance) — conservées dans le conteneur, non committées
  (même traitement que le corpus de 435 messages de l'audit d'origine).

## 19.2 Résultats chiffrés

| Mesure | Résultat |
|---|---|
| Accuracy globale (n=90) | **75,6 %** (68/90) |
| Référence — audit du 16 juillet (n=416) | 65,4 % |
| Référence — `tests/test_nlu.yml` (n=93) | 99,85 % |

Détail par intention (precision / recall / f1, triées par recall croissant) :

| Intention | Support | Precision | Recall | Confondue avec |
|---|---:|---:|---:|---|
| `ask_complaint_status` | 5 | 0 % | **0 %** | `create_reclamation` (3), `plainte` (1), `out_of_scope` (1) |
| `plainte` | 5 | 66,7 % | 40 % | `inappropriate_language` (2), `ask_faq` (1) |
| `greet` | 3 | 100 % | 66,7 % | `out_of_scope` (1) |
| `ask_faq` | 32 | 92,6 % | 78,1 % | `suggestion` (2), `out_of_scope` (2) |
| `create_reclamation` | 16 | 82,4 % | 87,5 % | `out_of_scope` (1), `bot_challenge` (1) |
| `suggestion` | 5 | 57,1 % | 80 % | `out_of_scope` (1) |
| `out_of_scope` | 8 | 53,8 % | 87,5 % | `ask_capabilities` (1) |
| `diagnostic` | 14 | 85,7 % | 85,7 % | `suggestion` (1), `ask_faq` (1) |
| `bot_challenge` | 2 | 66,7 % | 100 % | — |

Ce n'est pas une régression du système global par rapport au 65,4 % du 16
juillet (75,6 % ici, sur un corpus plus petit et différent — les deux
chiffres ne sont pas strictement comparables), mais l'écart avec les
99,85 % de `test_nlu.yml` reste très large, confirmant le diagnostic de
[16.5](16-audit-faq-nlu-2026-07.md#165-failles-identifiées-classées-par-impact) #2
sur un corpus indépendant supplémentaire.

## 19.3 Constat 1 — la collision `ask_faq`/`diagnostic` (P0) est toujours active

Reproduite en direct, sur une formulation volontairement différente de
celle de l'audit du 16 juillet :

> *"Comment récupérer l'accès à mon compte si j'ai oublié mon mot de passe ?"*
> → `diagnostic` (confiance **0,997**), attendu `ask_faq`.

C'est exactement le même motif d'échec que
[16.4](16-audit-faq-nlu-2026-07.md#164-échecs-représentatifs-extraits-texte-exact-envoyé)
("J'ai oublié mon mot de passe, comment le récupérer ?" → `diagnostic`
1.000), sur une formulation entièrement nouvelle. Malgré les modifications
apportées à `nlu.yml` entre le 16 et le 22 juillet (visibles dans les
commentaires du fichier, y compris un nettoyage daté du 22), **cette faille
précise n'est pas résolue à ce jour**. Deux autres cas de la même famille
dans ce corpus (registre familier : "jve cré 1 compte comen on fé" →
`out_of_scope` 0,9997 ; questions courtes : "Tarifs ?" → `affirm`, "Moyens
de paiement ?" / "Parrainage ?" → `suggestion`) confirment que
`ask_faq` reste la cible la plus fréquente de mauvaise classification du
corpus (5 des 22 erreurs), cohérent avec son rang 2 dans le classement du
chapitre 18.

**Conclusion pour la priorité P0 du chapitre 18** : reste ouverte, sans
correctif tenté dans cette session — voir [19.5](#195-décision-requise) pour
la suite proposée.

## 19.4 Constat 2 — le pilier Réclamation (P1) : un point fort et une faille sévère nouvellement mesurés

**Point fort inattendu** : `create_reclamation` tient bien la charge
adversariale (87,5 % de rappel, 82,4 % de précision sur 16 exemples,
incluant fautes de frappe lourdes type SMS : "jve k on ouvr 1 vrai dossié pr
mon problem" correctement classé). C'est la première mesure adversariale
réelle de ce pilier, comblant le trou identifié en
[18.3](18-rapport-competences.md#3-réclamation--suivi-de-ticket) — le
résultat est nettement meilleur que ce que laissait craindre l'absence de
mesure.

**Faille sévère, nouvellement quantifiée** : `ask_complaint_status`
échoue **100 % du temps** sur ce corpus (0/5), absorbée à très haute
confiance (jusqu'à 99,9 %) par `create_reclamation` :

> *"mon dossié davan sa en é ou"* → `create_reclamation` (0,9994)
> *"Vous pouvez me dire ce qui se passe avec le ticket que j'ai ouvert ?"* → `create_reclamation` (0,9936)

C'est plus grave que ce que le chapitre 18 avait anticipé : la proposition
P1 d'origine ("couvrir `ask_complaint_status` par les mêmes gardes que les
autres intentions méta", déjà appliquée dans `rasa/data/rules.yml` — voir
[19.6](#196-actions-déjà-appliquées-dans-cette-session)) corrige la
**gestion du dialogue** une fois l'intention reconnue, mais est **sans
effet** ici : le message n'est jamais classé `ask_complaint_status` en
premier lieu, donc aucune des règles (anciennes ou nouvelles) ne se
déclenche. Le vrai correctif est du côté des données d'entraînement — voir
19.6.

## 19.5 Décision requise

Ce chapitre confirme, avec des mesures fraîches, que le correctif de fond
pour la collision `ask_faq`/`diagnostic` reste à faire — et que
[16.6](16-audit-faq-nlu-2026-07.md#166-plan-damélioration-priorisé) a déjà
documenté qu'une correction naïve par les données (ajout d'exemples
`ask_faq`) **régresse** l'exactitude globale (-2.4pt puis -2.2pt, avec un
effet collatéral -20pt sur `out_of_scope` sans qu'aucun exemple de cette
intention n'ait été touché). La seule piste avec un gain mesuré positif
(embeddings denses CamemBERT en complément du bag-of-words, +1.2pt) a un
coût de latence ~15-20x et n'est pas industrialisée.

**Cette session n'a pas tenté de correctif sur ce point** — l'ajouter au
pipeline NLU (nouveau featurizer, réentraînement complet, remplacement du
modèle actuellement servi par le conteneur `pfe-rasa-1`) est un changement
d'architecture avec un coût de performance réel et un historique documenté
d'échecs, sur un système actuellement en cours d'exécution. Il revient au
mainteneur du projet de décider s'il souhaite : (a) lancer l'expérimentation
CamemBERT dans un cadre contrôlé (mesurer d'abord le coût de latence réel
sur ce volume de catalogue), (b) accepter cette limite pour l'instant et se
concentrer sur les corrections à moindre risque listées en 19.6, ou (c) une
autre direction.

## 19.6 Actions déjà appliquées dans cette session

En cohérence avec les priorités du chapitre 18, appliquées avant ou après ce
test (voir historique Git pour le détail exact) :

- **P1** — Règles `rules.yml` manquantes pour `ask_complaint_status`
  ("while diagnostic is pending" / "while reclamation form is active"),
  alignées sur le pattern déjà en place pour `bot_challenge`/`suggestion`.
  Nécessaire mais **non suffisant** au vu de 19.4 — la NLU doit d'abord
  reconnaître l'intention.
- **P1** — 14 nouveaux exemples `ask_complaint_status` ajoutés à
  `nlu.yml`, ciblant précisément le vocabulaire manquant identifié ici
  ("dossier", tournures au passé "j'ai déjà...", registre SMS) — **pas
  encore réentraînés/mesurés** : voir la mise en garde de
  [16.6](16-audit-faq-nlu-2026-07.md#166-plan-damélioration-priorisé) sur les
  effets globaux imprévisibles d'une modification de `nlu.yml`. Une
  ré-exécution de `rasa test nlu` sur ce même corpus adversarial, après
  réentraînement, est nécessaire pour confirmer que cet ajout améliore bien
  `ask_complaint_status` sans dégrader une autre intention (le risque exact
  que 16.6 a déjà documenté sur `ask_faq`/`out_of_scope`).
- **P1** — Clarification/enrichissement `select_faq_category` (8 catégories
  sur 12 sans exemple auparavant) et documentation explicite du design
  bouton-only de `select_faq_question`.
- **P2** — Suppression de 11 slots dormants et de l'entité `urgency` (0
  exemple annoté, aucun mapping actif) — `rasa data validate` repasse sans
  erreur après ce nettoyage.

**Aucun de ces changements n'a encore été réentraîné ni redéployé** sur le
conteneur `pfe-rasa-1` : le modèle actuellement servi (`test-audit-quick.tar.gz`)
ne les reflète pas encore. `rasa data validate` confirme seulement que les
fichiers restent cohérents entre eux, pas que le modèle en production les
intègre.

---

Suite : [20. Réentraînement v7 et abandon de CamemBERT](20-rapport-retrain-v7.md)
