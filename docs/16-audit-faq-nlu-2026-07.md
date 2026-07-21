← [Sommaire](README.md) | [15. Modèle de données](15-modele-donnees.md)

# 16. Audit qualité NLU + FAQ retrieval (2026-07-21)

Audit exécuté en conditions réelles (pas une revue de code statique) : 435
messages envoyés à l'instance Rasa NLU locale (`POST /model/parse`, port
5005) et au moteur de recherche FAQ FastAPI+PGVector (`POST /faq/search`,
port 8000), tous deux tournant sur les mêmes conteneurs/process que ceux
utilisés en développement. Catalogue FAQ interrogé : les 31 lignes réelles
de `core.faq_items` en base au moment du test (26 questions distinctes, voir
[16.2](#162-anomalie-de-données--doublons-dans-le-catalogue-faq)).

Contrairement à `rasa/tests/test_nlu.yml` (24 exemples `ask_faq`, écrits par
la même personne/session que les données d'entraînement), le corpus de cet
audit a été conçu pour être **adversarial** : reformulations naturelles,
fautes de frappe injectées, registre familier/SMS, questions ambiguës ou
tronquées, messages longs mélangeant plusieurs intentions, paires
sémantiquement proches mais avec des réponses différentes, cas limites
(emoji, injection, langues étrangères), et messages testant la frontière
entre `ask_faq` et les autres intentions (`create_reclamation`, `diagnostic`,
`greet`...).

Script générateur, harness d'exécution et résultats bruts :
`tests_400.csv` / `results.csv` (435 lignes, disponibles sur demande — non
committés dans ce dépôt).

## 16.1 Résultats chiffrés

| Mesure | Résultat | Référence existante |
|---|---|---|
| Accuracy intent NLU (corpus adversarial, n=416) | **65,4 %** (272/416) | 99,85 % sur `rasa/tests/test_nlu.yml` (`rasa/results/intent_report.json`) |
| FAQ retrieval Top-1 (n=306, question avec FAQ attendue) | **57,8 %** (177/306) | Seuil calibré à 0,85 sur 15 questions + 10 négatifs (voir `service.py`) |
| — dont "wrong match" (réponse confiante mais fausse FAQ, score ≥ 0,85) | 13,4 % (41/306) | — |
| — dont "not found" (échec de rappel, score < 0,85) | 28,8 % (88/306) | — |
| Faux positifs FAQ (réponse servie avec confiance sur un message qui ne devrait PAS en recevoir une) | 28 cas | — |
| Scores de similarité dans [0,85 ; 0,90) parmi les matches | 214/246 = **87 %** | — |

**Lecture du premier chiffre : l'écart 65,4 % vs 99,85 % est le résultat le
plus important de cet audit.** Il ne signifie pas que le modèle s'est
dégradé — il montre que le jeu de test existant (`test_nlu.yml`), bien
qu'indépendant du fichier d'entraînement au sens strict (pas de phrase
dupliquée), partage un style et un vocabulaire trop proches de celui-ci pour
mesurer la robustesse réelle face à un utilisateur qui tape avec ses propres
mots, ses fautes, et son registre. C'est une fuite de style, pas de données
— un antipattern classique en évaluation NLU, plus difficile à détecter
qu'une fuite de données brute car aucune phrase n'est identique de part et
d'autre.

Détail par catégorie (accuracy intent) :

| Catégorie | Accuracy intent | Accuracy retrieval (si FAQ attendue) |
|---|---|---|
| A. Reformulations naturelles (n=130) | 76,2 % | 70,0 % |
| B. Fautes de frappe (n=78) | 76,9 % | 60,3 % |
| C. Registre familier / SMS (n=52) | 67,3 % | 40,4 % |
| D. Questions courtes/ambiguës (n=20 avec vérité terrain) | 25,0 % | 7,7 % |
| E. Messages longs multi-intentions (n=25) | 20,0 % | — |
| F. Hors domaine (n=30) | 66,7 % | — |
| G. Proches sémantiquement (n=30) | 56,7 % | 42,9 % |
| H. Cas limites (n=21 avec vérité terrain) | 66,7 % | 57,1 % |
| I. Frontière avec d'autres intentions (n=30) | 56,7 % | — |

## 16.2 Anomalie de données : doublons dans le catalogue FAQ

5 des 31 lignes de `core.faq_items` sont des **doublons exacts** (même
question, même réponse, `slug` différent) : "Puis-je utiliser NGONI sur
plusieurs appareils ?", "Où trouver la foire aux questions ?", "Comment un
créateur peut-il gagner de l'argent sur la plateforme ?", "Comment fonctionne
le système de dons pendant un live ?", "Quels documents sont nécessaires
pour le KYC ?" — soit **16 % du catalogue**. Les réponses sont identiques
aujourd'hui (pas de divergence de contenu constatée), mais :
- toute future édition d'une des deux lignes sans toucher l'autre créera une
  incohérence silencieuse (deux réponses différentes à la même question,
  résultat non déterministe côté `find_closest` en cas d'égalité de score) ;
- `/faq/random` (message d'accueil) et `/faq/suggestions` (parcours par
  catégorie) peuvent tirer les deux doublons dans le même lot, affichant
  deux fois "la même" question suggérée à l'utilisateur.

## 16.3 Bug confirmé en conditions réelles : `fastapi` non fonctionnel via `docker-compose`

En tentant de faire tourner l'ensemble de la stack via `docker compose up`,
le service `fastapi` démarre mais ne peut jamais atteindre Rasa ni Postgres :
`fastapi/.env` fixe `RASA_PARSE_URL`, `RASA_WEBHOOK_URL` et `DATABASE_URL`
sur `127.0.0.1`, qui à l'intérieur du conteneur `fastapi` pointe vers
lui-même, pas vers les conteneurs `rasa`/`postgres`. `docker-compose.yml` ne
compense pas : seul `DATABASE_URL` est réinjecté via `environment:`, pas les
deux URLs Rasa. À l'inverse, `rasa/actions/.env` et `rasa/.env` utilisent
`host.docker.internal`, cohérent uniquement avec un FastAPI tournant
**nativement sur l'hôte** (le `.venv` déjà présent dans `fastapi/`) — ce
qui est le mode de fonctionnement réel utilisé pour cet audit, confirmé
avec toi en cours de session. **Le service `fastapi` du `docker-compose.yml`
est donc mort tel quel** : quiconque suit le chemin "tout Docker" documenté
implicitement par sa seule présence dans le fichier obtient un `/api/chat`
qui échoue à 100 % avec `502 Impossible de contacter Rasa`.

## 16.4 Échecs représentatifs (extraits, texte exact envoyé)

**NLU — `ask_faq` absorbé par `diagnostic` (le motif d'échec le plus
fréquent du corpus)** :
- *"J'ai oublié mon mot de passe, comment le récupérer ?"* → `diagnostic` (conf. 1.000), attendu `ask_faq`
- *"Que reçoit un créateur quand on lui envoie un don en live ?"* → `diagnostic` (1.000)
- *"Mon compte n'est pas vérifié, comment y remédier ?"* → `diagnostic` (1.000)
- *"Comment un créateur génère des revenus ssur NGONI ?"* (faute injectée) → `diagnostic`

**NLU — questions courtes/elliptiques (le pire score du corpus, 25 %)** :
- *"Retrait ?"* → `diagnostic` (1.000) ; *"Paiement"* → `diagnostic` (1.000) ; *"KYC"* → `diagnostic` (1.000) ; *"Langue"* → `suggestion` (1.000) ; *"Aide"* → `greet` (0.962)

**NLU — hors-domaine classé avec une confiance totale dans une intention métier** :
- *"Comment fait-on pour apprendre le piano rapidement ?"* → `ask_faq` (conf. 1.000)
- *"Est-ce que tu peux commander une pizza pour moi ?"* → `create_reclamation` (conf. 1.000)
- *"Peux-tu m'aider à réviser mon examen de chimie ?"* → `create_reclamation` (conf. 1.000)

**Retrieval — faux positif dangereux (score ≥ seuil, mauvaise FAQ, information
potentiellement incorrecte servie avec confiance)** :
- *"Comment gagner des pièces en regardant du contenu ?"* → matché à **"Comment acheter des pièces NGONI ?"** (0,855) — répond "achetez des pièces" à une question sur le fait d'en **gagner**, sens quasi opposé.
- *"Mon compte est bloqué, comment le débloquer ?"* → matché à **"Comment obtenir la vérification de mon compte ?"** (0,860) — une plainte de blocage reçoit une procédure de vérification standard, pas d'escalade.
- Chacun des 15 messages longs "FAQ + incident concret" (catégorie E) matche
  sa FAQ générique avec un score ≥ 0,85 (0,855–0,906) — si jamais l'intention
  `ask_faq` est retenue en amont sur ce type de message, la couche retrieval
  **confirmerait** une réponse générique là où l'utilisateur décrit un
  incident précis nécessitant une réclamation.

**Retrieval — recall quasi nul sur le registre familier (55,8 % de `not_found`)** :
- *"Cmt on fait pour sortir largent du compte"*, *"Comment javoir le badge bleu"*, *"Jai zap mon mdp comment faire"*, *"Ou est la faq stp"* → toutes en `not_found`, alors que les paraphrases correctement orthographiées des mêmes sujets passent le seuil sans problème.

## 16.5 Failles identifiées (classées par impact)

1. **[Critique] Chevauchement d'entraînement `ask_faq` / `diagnostic`.**
   Le motif d'échec le plus fréquent et le plus systématique du corpus : dès
   qu'une question FAQ légitime contient du vocabulaire de type
   "compte / mot de passe / retrait / vérifier / connexion", DIET la classe
   en `diagnostic` avec une confiance proche de 1.0, quel que soit le
   nombre d'exemples `ask_faq` déjà présents (175 dans `nlu.yml`). Le
   problème n'est pas la quantité d'exemples `ask_faq` mais l'absence
   d'exemples `ask_faq` qui *ressemblent lexicalement* à des exemples
   `diagnostic` existants — DIET a appris à trancher sur des mots-clés
   plutôt que sur l'intention réelle derrière la phrase.

2. **[Critique] Le jeu de test NLU existant surestime la robustesse réelle.**
   99,85 % sur `test_nlu.yml` vs 65,4 % sur un corpus adversarial construit
   sur les mêmes 26 sujets FAQ réels. Toute décision produit basée
   uniquement sur `intent_report.json` (ex. "le NLU est prêt pour la
   prod") repose sur une mesure qui ne reflète pas l'usage réel.

3. **[Élevé] Seuil de similarité FAQ (0,85) calibré sur un échantillon trop
   petit pour être fiable — confirmé empiriquement.** 87 % des matches
   valides tombent dans la fenêtre [0,85 ; 0,90), une plage de 5 centièmes :
   la frontière accepté/refusé tient à des variations de formulation
   mineures. Le taux de faux positifs mesuré ici (13,4 % des cas avec FAQ
   attendue) est bien au-dessus du 0 % mesuré lors de la calibration
   d'origine (15 questions + 10 négatifs, voir commentaire dans
   `service.py`) — l'échantillon d'origine était trop petit pour détecter ce
   taux d'erreur.

4. **[Élevé] Recall quasi nul sur le registre familier/SMS** (55,8 % de
   `not_found` en catégorie C) — un pan entier et courant du langage réel
   des utilisateurs (abréviations, absence d'accents, "cmt", "jveux"...)
   n'atteint jamais le seuil de similarité, même quand la question porte
   sur une FAQ existante.

5. **[Moyen] Aucune stratégie explicite pour les messages
   multi-intentions.** Aucun découpage de clause, aucune détection de
   "cette phrase contient une vraie urgence en plus d'une question
   générale" : le système traite le message comme un bloc unique et
   choisit une seule intention gagnante, perdant l'information secondaire
   dans 100 % des cas testés (catégorie E).

6. **[Moyen] Questions courtes/elliptiques non gérées** (25 % d'accuracy,
   pire score du corpus) — aucune clarification n'est demandée, le système
   tranche directement et se trompe dans 3 cas sur 4 sur des requêtes
   pourtant très courantes en usage mobile réel ("Retrait ?", "KYC",
   "Aide").

7. **[Moyen] Retrieval mono-champ (question uniquement).** `find_closest`
   ne compare que l'embedding de `question` — jamais `keywords` (colonne
   existante, `ARRAY(Text)`, actuellement écrite mais jamais lue en
   recherche) ni le contenu de `answer`. Une recherche hybride
   lexical+sémantique récupérerait probablement une partie des cas
   `not_found` de la catégorie C (ex. "cmt on sinscri sur ngoni" partage
   viii le mot-clé "compte"/"inscription" même quand l'embedding s'éloigne
   trop du seuil).

8. **[Moyen] `find_closest` ne renvoie que le Top-1.** Impossible de mesurer
   Top-3 (demandé dans le brief d'audit initial) sans modifier la requête
   SQL (`LIMIT 1` en dur) — c'est aussi une limite fonctionnelle réelle :
   il n'existe aujourd'hui aucun mécanisme de "vouliez-vous dire..." avec
   les candidats suivants quand le Top-1 est sous le seuil.

9. **[Mineur, déjà documenté] Portée mono-langue confirmée
   empiriquement** ([13.5](13-limitations.md#135-portée-mono-langue)) :
   "How do I withdraw my earnings on NGONI?" classé `out_of_scope`
   (conf. 0,999) malgré la présence du mot "NGONI".

10. **[Mineur] Doublons de catalogue FAQ** — voir [16.2](#162-anomalie-de-données--doublons-dans-le-catalogue-faq).

11. **[Mineur] `docker-compose.yml` : service `fastapi` non fonctionnel** —
    voir [16.3](#163-bug-confirmé-en-conditions-réelles--fastapi-non-fonctionnel-via-docker-compose).
    Classé mineur uniquement parce que ce n'est pas le mode d'exécution réel
    utilisé (FastAPI tourne nativement) — mais reste un piège pour quiconque
    reproduit l'environnement à partir du seul `docker-compose.yml`.

## 16.6 Plan d'amélioration priorisé

### P0 — Critique (bloquant avant toute mise en production)

- **Retraiter le chevauchement `ask_faq`/`diagnostic`.** ⚠️ **Tenté le soir
  même de cet audit, résultat négatif — voir
  [16.8](#168-post-scriptum--tentatives-de-correctif-expérimentées-le-soir-même).**
  Nettoyer/enrichir les exemples `ask_faq` (2 puis 30 exemples ajoutés) a
  régressé l'accuracy globale à chaque fois (-2.4pt puis -2.2pt) au lieu de
  l'améliorer : sur un pipeline bag-of-words, une modification locale des
  données d'entraînement a des effets globaux imprévisibles, y compris sur
  des intentions non touchées (`out_of_scope` a régressé de -20pt sans
  qu'aucun de ses exemples n'ait été modifié). Piste alternative validée
  avec un gain réel mais modeste (+1.2pt) : ajouter des embeddings denses
  (CamemBERT) en plus du bag-of-words — voir 16.8 pour le détail et les
  conditions avant adoption (coût de latence ~15-20x mesuré, non
  industrialisé).
- **Remplacer/compléter le jeu de test NLU par un corpus indépendant**,
  construit par une personne/session différente de celle qui écrit les
  données d'entraînement (ou à défaut, avec le corpus de cet audit comme
  jeu de non-régression permanent). Sans ça, tout futur changement de
  pipeline continuera d'être validé sur une mesure trompeuse.
- **Documenter/retirer le service `fastapi` du `docker-compose.yml`**
  tel quel : soit corriger `fastapi/.env` pour une vraie exécution
  conteneurisée (variante `DATABASE_URL`/`RASA_*` par profil), soit
  supprimer ce service du compose et documenter explicitement "FastAPI
  tourne nativement, seuls Rasa/actions/Postgres sont dockerisés" pour
  éviter qu'un futur contributeur ne perde du temps sur un service mort.

### P1 — Haute priorité (fort impact qualité)

- **Recalibrer `DEFAULT_THRESHOLD`** sur les 306 paires question/FAQ
  attendue de ce corpus (bien au-delà des 15+10 d'origine) : tracer
  précision/rappel pour plusieurs seuils (0,80 à 0,88) et choisir le point
  qui réduit le taux de faux positifs mesuré (13,4 %) sans sacrifier
  excessivement le rappel déjà faible (57,8 %). Nécessite d'abord
  d'exposer le score même sous le seuil actuel (endpoint de debug ou log)
  pour pouvoir rejouer la courbe sans reconfigurer `DEFAULT_THRESHOLD` à
  chaque essai.
- **Recherche hybride lexicale + sémantique** : utiliser la colonne
  `keywords` (déjà en base, jamais lue) en filtre/boost complémentaire à la
  similarité cosinus, en particulier pour rattraper les cas `not_found` du
  registre familier où l'orthographe dégradée fait décrocher l'embedding
  mais où un mot-clé exact reste présent.
- **Étendre `find_closest` à un Top-3** avec un second seuil plus bas
  (ex. 0,75) pour proposer "Vouliez-vous dire : [Q1] / [Q2] / [Q3] ?" plutôt
  que "je n'ai pas trouvé" sec — transforme une partie des 28,8 % de
  `not_found` en clarification utile au lieu d'un échec silencieux.
- **Dédupliquer le catalogue FAQ** (5 paires identifiées) et ajouter une
  contrainte applicative (ou un test) qui détecte toute nouvelle
  quasi-duplication à l'ajout d'une FAQ (similarité cosinus entre la
  nouvelle question et les questions existantes, au-dessus d'un seuil
  élevé type 0,97 → avertissement de doublon probable).
- **Détection de "message composite"** : avant classification, repérer les
  signaux de sévérité/urgence concrète (montant, date précise, "depuis
  X jours", "bloqué", "piraté"...) et, si présents en même temps qu'un
  intent `ask_faq`, proposer explicitement les deux issues ("Voici la
  réponse générale : [FAQ] — mais si votre cas précis n'est pas résolu,
  voulez-vous ouvrir une réclamation ?") plutôt que de arbitrer en silence
  entre les deux.

### P2 — Optimisation (performance, coût, maintenabilité)

- **Gestion explicite des messages courts/elliptiques** (< 3 mots) : les
  router vers une clarification dédiée ("Vous voulez dire : retirer de
  l'argent, ou consulter les délais de retrait ?") plutôt que vers le
  DIET pur, qui n'a statistiquement quasiment aucune chance de bien
  trancher sur un seul mot ambigu (25 % d'accuracy mesurée ici).
  Techniquement : router sur le nombre de tokens avant même l'appel DIET,
  vers `browse_faq`/une recherche par mot-clé sur `keywords` plutôt que
  sur l'embedding complet d'une phrase à un seul mot.
  Non prioritaire par rapport à P0/P1 : rare mais gérable via une simple
  redirection à moindre risque, à la différence du chevauchement
  `ask_faq`/`diagnostic` qui touche des questions bien formées.
- **Index `ivfflat`/`hnsw` sur `embedding`** : à ce jour prématuré (31
  lignes, déjà noté dans `repository.py`) mais à planifier dès que le
  catalogue dépasse quelques centaines d'entrées.
- **Non-régression automatisée FAQ** : il n'existe aujourd'hui aucun
  `tests/test_faq_*.py` (contrairement au domaine diagnostic, qui en a
  10). Ce corpus de 435 messages, réduit à un sous-ensemble stable
  (~50-80 cas couvrant chaque catégorie), ferait un bon point de départ
  pour un test de non-régression exécuté en CI contre un `FaqRepository`
  de test.

## 16.7 Nouvelles perspectives d'amélioration

**Boucle d'apprentissage à partir des notations réelles.** `core.faq_items`
et le mécanisme `pending_ratings`/`response_ratings` capturent déjà
"utile/pas utile" par réponse FAQ servie, et `audit.agent_actions` journalise
déjà chaque `question` + `matched_question` + `score` réel (voir
`record_faq_lookup`). Cette donnée existe mais n'est exploitée nulle part
aujourd'hui : un rapport hebdomadaire simple ("questions posées sans FAQ
trouvée, triées par fréquence" + "réponses notées 'pas utile' avec leur
score de similarité") transformerait chaque usage réel en signal de
correction du catalogue et du seuil, sans attendre un audit ponctuel comme
celui-ci.

**Ré-évaluer l'architecture hybride Rasa+embeddings face à un pipeline
LLM/RAG, sujet par sujet plutôt que globalement.** Les résultats de cet
audit permettent de trancher avec des chiffres plutôt qu'avec une intuition :
- La classification d'intention (Rasa/DIET) reste défendable pour les
  intentions *procédurales* bien délimitées (`greet`, `bot_challenge`,
  `affirm`/`deny`, déclenchement de formulaire) — ce sont elles qui
  scorent bien même dans ce corpus adversarial.
- En revanche, la frontière `ask_faq` vs `diagnostic` vs `create_reclamation`
  — précisément le point le plus faible mesuré ici — est un problème de
  *compréhension contextuelle*, pas de correspondance de motifs : un LLM
  généraliste (même petit, type appel API ponctuel plutôt que réentraînement
  DIET) tranche nativement ce genre d'ambiguïté sans qu'il faille lui fournir
  des centaines d'exemples par cas limite.
- Le retrieval FAQ lui-même gagnerait plus d'un **re-ranking léger par LLM
  sur les 3 meilleurs candidats PGVector** (coût : un seul appel court, pas
  un système RAG complet) que d'un changement de modèle d'embedding : le
  problème mesuré n'est pas "l'embedding ne trouve pas de candidat
  plausible" (`find_closest` ramène presque toujours quelque chose de
  thématiquement proche) mais "le Top-1 par cosinus n'est pas toujours le
  bon". Une architecture *retrieval PGVector (rapide, déjà en place) + LLM
  pour départager/reformuler le dernier mètre* capitalise sur l'existant
  plutôt que de le remplacer.
- Recommandation concrète : ne pas migrer tout le pipeline vers un LLM
  généraliste (coût, latence, dépendance externe pour un service qui tourne
  aujourd'hui 100 % local) — cibler un **LLM en re-ranking/désambiguïsation
  ponctuelle** sur les deux points faibles mesurés (frontière d'intention
  ask_faq/diagnostic/reclamation, et arbitrage du Top-3 retrieval), en
  gardant Rasa pour tout le reste du flux conversationnel (formulaires,
  slots, boutons) où il fonctionne déjà bien.

**Auto-expansion du catalogue FAQ à partir des `not_found` récurrents.**
Les 88 cas `not_found` de ce seul audit, une fois dédupliqués par sujet,
dessinent déjà des variantes de formulation qui pourraient être ajoutées
comme exemples d'entraînement `ask_faq` (pas comme nouvelles FAQ — les
sujets existent déjà, c'est la reconnaissance qui manque). Un processus
récurrent (mensuel, sur les vraies requêtes journalisées en prod plutôt que
sur un corpus synthétique) fermerait cette boucle sans audit manuel répété.

**Détection de duplication à l'écriture, pas seulement en lecture.** Le
correctif ponctuel des 5 doublons actuels (P1) ne doit pas être la seule
protection : brancher la même vérification de similarité cosinus utilisée
pour la recherche sur le chemin d'écriture (`FaqService.add_faq`) empêche
la réapparition du problème à chaque nouvel ajout, humain ou en masse
(`POST /faq/` accepte déjà un batch complet).

## 16.8 Post-scriptum : tentatives de correctif expérimentées le soir même

Suite à la rédaction de ce rapport, trois pistes de correctif sur le
chevauchement `ask_faq`/`diagnostic` (16.5, faille #1) ont été testées et
mesurées **le soir même**, avant tout commit. Documenté ici par souci
d'exhaustivité — deux résultats négatifs, un positif mais coûteux — pour
qu'une prochaine tentative ne reparte pas de zéro sur les mêmes hypothèses.

### v1 — nettoyage ciblé (2 exemples)

Mesure par recouvrement de mots-contenu (Jaccard) entre les 174 exemples
`ask_faq` et 387 `diagnostic` de `rasa/data/nlu.yml` : 2 exemples `ask_faq`
identifiés comme du bruit d'étiquetage réel (structurellement identiques au
patron dominant de `diagnostic`, "Pourquoi mon [sujet] [état problème] ?").
Retirés/reformulés, modèle réentraîné (`rasa train nlu`, 80 epochs, ~1h20).

**Résultat : -2,4 pts d'accuracy globale** (65,4 % → 63,0 %) sur le corpus
adversarial de 435 messages, et -4,0 pts sur le sous-ensemble
`ask_faq`/`diagnostic` (71,1 % → 67,1 %). Seulement 3 cas corrigés contre 35
régressions nettes.

### v2 — nettoyage à plus grande échelle (+28 exemples)

Hypothèse : l'effet de levier de v1 était trop faible (2 exemples sur 561).
Ajout de 28 exemples `ask_faq` génériques/procéduraux couvrant des zones de
vocabulaire jusque-là exclusivement occupées par `diagnostic` (dépôt,
transfert, messagerie, notifications, suspension, conformité, consentement
parental) — vocabulaire confirmé absent d'`ask_faq` par grep direct avant
l'ajout. Réentraîné (~1h11).

**Résultat : toujours -2,2 pts** (63,2 % global, 69,6 % sur le sous-ensemble
ciblé), avec une régression inattendue et non ciblée sur `F_hors_domaine`
(-20 pts, 67 %→47 %) — des messages hors-sujet formulés normalement se sont
mis à matcher `ask_faq`/`diagnostic` à cause du vocabulaire générique ajouté
("en général", "quelle est la procédure"...), qui a réduit l'efficacité du
`VocabularyCoverageGuard` à isoler le hors-vocabulaire.

**Enseignement méthodologique** : sur un pipeline bag-of-words/char-n-gram
à ~2000 exemples, la frontière de décision est globalement instable — modifier
quelques exemples dans un coin du dataset produit des ondulations
imprévisibles ailleurs, démontrable seulement en re-testant intégralement
après coup (~1h30 par cycle sur cette machine). Aucune mesure de variance
témoin (réentraînement à données inchangées) n'a été faite pour quantifier
la part de bruit stochastique dans ces deux résultats négatifs — limite
reconnue de cette expérimentation.

Modèle remis à l'original (`retrained-audit-fixes-v6.tar.gz`) après chaque
tentative ; les modèles v1/v2 sont conservés dans
`rasa/models/experiments/` pour référence. Les 30 exemples ajoutés à
`nlu.yml` (v1+v2) sont restés dans le fichier (décision de les garder ou non
encore ouverte) et servent de base à la troisième tentative ci-dessous.

### Piste 3 — embeddings denses (CamemBERT) en complément du bag-of-words

Root cause reconsidérée : `config.yml` n'alimente `DIETClassifier` qu'avec
des featurizers bag-of-words/char-n-gram (`CountVectorsFeaturizer`), aucun
embedding sémantique. Ajout d'un `LanguageModelFeaturizer` (CamemBERT — le
seul modèle français natif du registre Rasa 3.6.20 parmi
`bert/gpt/gpt2/xlnet/distilbert/roberta/camembert` ; `intfloat/multilingual-
e5-base`, déjà utilisé côté FastAPI, est architecture XLM-RoBERTa, non
supportée par ce registre) **en plus** du bag-of-words existant, pas en
remplacement (le char-n-gram reste seul responsable de la tolérance aux
fautes de frappe sévères).

**Validation en deux temps** :
1. Cross-validation réduite (2 plis, 30 epochs, sous-ensemble
   `ask_faq`+`diagnostic` seul) : 93,5 % → **95,1 %** — signal positif, mais
   ce chiffre mesure la généralisation intra-distribution, pas comparable
   au 65,4 %/71,1 % du corpus adversarial.
2. Essai complet (80 epochs, `nlu.yml` entier) puis remesure sur les 435
   messages : **65,4 % → 66,6 %** (+1,2 pt global), **71,1 % → 72,0 %**
   (+0,9 pt sur le sous-ensemble ciblé). 27 gains contre 22 régressions net
   +5. Gain le plus net sur `G_proche_semantique` (paires confusables,
   +7 pts) — cohérent avec l'hypothèse. `D_court_ambigu` reste inchangé
   (0 pt, problème différent). Le chevauchement `diagnostic`→`ask_faq`
   n'est que partiellement corrigé, pas résolu : le déséquilibre de volume
   (387 exemples `diagnostic` vs ~210 `ask_faq`) domine toujours une partie
   des cas.

**Coût mesuré, pas seulement théorique** : le temps de réponse `/model/parse`
est passé d'environ 0,05-0,07 s à **~0,95 s par message** (15-20x), rien que
pour le NLU, avant l'appel FastAPI/PGVector. `transformers==4.26.0`,
`sentencepiece` et les poids CamemBERT (~450 Mo) ont été installés
manuellement dans le conteneur en cours d'exécution, **pas dans
`rasa/Dockerfile`** — ce modèle ne survivrait pas à une reconstruction de
l'image depuis zéro sans que ces dépendances y soient ajoutées.

**Décision** : modèle remis à `retrained-audit-fixes-v6.tar.gz`, le modèle
CamemBERT conservé dans `rasa/models/experiments/faq-diagnostic-embedding-v1.tar.gz`
pour référence. Gain jugé réel mais insuffisant pour justifier le coût de
latence et la dette d'industrialisation sans une décision produit explicite
sur l'acceptabilité de ~1s de latence NLU supplémentaire. **Conditions avant
adoption future** : (1) mesurer la latence bout-en-bout réelle perçue par
l'utilisateur (pas seulement `/model/parse` isolé), (2) si acceptée,
figer les dépendances dans `rasa/Dockerfile`/`requirements` plutôt que dans
l'environnement du conteneur vivant, (3) traiter en parallèle le
déséquilibre de volume `diagnostic`/`ask_faq` (387 vs 210) qui limite le
gain même avec des embeddings, (4) envisager un modèle plus petit
(`distilbert`, supporté par le même registre) pour réduire le coût de
latence si le gain de précision se maintient.

---

Suite : [17. (à définir)](README.md)
