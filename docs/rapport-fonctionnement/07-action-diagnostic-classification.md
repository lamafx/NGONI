← [6. Rasa Core, policies, domaine](06-rasa-core-policies-domain.md) | → [8. Diagnostic — exécution de l'action](08-action-diagnostic-execution.md)

# 7. Diagnostic — classification sémantique

> **Rôle de ce document** : l'algorithme précis qui identifie **quel**
> problème (service + problème) décrit un message utilisateur libre —
> le fichier le plus élaboré du projet (`rasa/actions/diagnostic.py`,
> 3143 lignes). L'exécution qui suit une fois le problème identifié est au
> [chapitre 8](08-action-diagnostic-execution.md).

## Pourquoi ce n'est pas trivial

Un utilisateur décrit son problème en langage libre ("mon retrait est
bloqué depuis hier"), jamais avec le nom exact d'un `problem_id`. Il faut
retrouver, parmi le catalogue exposé par `GET /diagnostic/capabilities`
(voir [13. Le registre](13-diagnostic-engine-registry.md)), quel couple
(service, problème) correspond — avec gestion des synonymes, des messages à
plusieurs problèmes, des négations, et un repli si le service d'embeddings
est en panne.

## L'ordre des étapes (`_score_capabilities`)

1. **Embeddings d'abord** (`_score_capabilities_embeddings`) : similarité
   cosinus entre l'embedding du message et celui de la description +
   phrases d'exemple de chaque problème. Seuil retenu : **0.75**
   (`MIN_EMBEDDING_SIMILARITY`, recalibré le 2026-07-30 sur un corpus de 72
   requêtes ciblant des collisions déjà documentées — 0 faux positif,
   F1 = 0.990, meilleur de tout le balayage 0.65 à 0.85 testé).
2. **Repli par proposition** (`_score_capabilities_embeddings_by_clause`),
   déclenché seulement si aucun gagnant net : un message à plusieurs
   propositions ("mon retrait est bloqué **et** je voudrais comprendre
   pourquoi") dilue le vecteur moyen. Chaque proposition, découpée sur des
   connecteurs grammaticaux universels (et/mais/car/donc/puisque/alors
   que/cependant/parce que/par contre/en revanche — jamais du vocabulaire
   métier), est réembeddée séparément ; le meilleur score par problème,
   toutes propositions confondues, l'emporte.
3. **Filtre négation/résolution** (`_filter_negated_or_resolved`),
   **appliqué à tous les candidats**, pas seulement en cas d'égalité : un
   problème dont tous les mots-clés présents dans le message sont niés
   ("mon KYC **n'est plus** un souci") ou annoncés résolus est retiré, même
   avec un score net. Restreint à une liste explicite d'adjectifs/participes
   d'état négatifs (bloqué, suspendu, banni, refusé, rejeté) — pas une
   négation générique, pour distinguer "n'est plus bloqué" (résolution) de
   "n'est pas créditée" (problème toujours actif), grammaticalement
   identiques.
4. **Désambiguïsation inter-services** (`_apply_service_family_tiebreak`) :
   si le désaccord vient de candidats de services **différents** plutôt
   que d'une vraie ambiguïté interne à un service, restreint le bassin au
   service en tête (marge relative ≥ 2%, `CLASSIFICATION_RELATIVE_MARGIN`).
5. **Repli mot-clé en cas d'égalité** (`_apply_keyword_tiebreak`) :
   n'intervient que si les embeddings n'ont pas déjà un gagnant net — si un
   seul candidat parmi les 3 mieux placés a un signal lexical décisif, il
   gagne.
6. **Repêchage par mot-clé unique** (`_rescue_unique_keyword_match`),
   dernier recours si tout le reste échoue : un mot-clé sans ambiguïté
   (ex. "kyc") dont le score embedding réel dépasse un second plancher plus
   bas (0.40, `KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY`) est promu — mais
   seulement si un **seul** problème de tout le catalogue a ce signal.
7. **Repli mots-clés pur** (`_score_capabilities_keywords`), si le service
   d'embeddings est injoignable ou qu'aucun problème connu n'a d'embedding
   précalculé.

## Segmentation multi-problèmes

`_score_capabilities_multi` tente d'abord de découper le message sur de la
ponctuation forte (`.!?;` ou saut de ligne — pas des connecteurs comme
"aussi", trop ambigus grammaticalement) : un message énumérant plusieurs
problèmes distincts ("Je ne peux plus me connecter. Mon retrait est aussi en
attente.") est ainsi détecté comme tel plutôt que dilué en un seul score
sur le texte entier.

## Ce que ce chapitre ne couvre pas

Une fois le problème identifié et les champs requis obtenus, l'exécution
réelle (appel au Diagnostic Engine, gestion de l'escalade) est décrite au
[chapitre 8](08-action-diagnostic-execution.md).
