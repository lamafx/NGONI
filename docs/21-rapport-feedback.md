← [Sommaire](README.md) | [20. Réentraînement v7 et abandon de CamemBERT](20-rapport-retrain-v7.md)

# 21. Boucle de feedback hebdomadaire (2026-07-23)

Suite de [16.7](16-audit-faq-nlu-2026-07.md#167-nouvelles-perspectives-damélioration)
et de [docs/taches.txt](taches.txt) P1 #5 : `audit.agent_actions` et
`feedback.response_ratings` journalisent déjà chaque recherche FAQ et chaque
notation utile/pas utile, mais cette donnée n'était exploitée nulle part.
Nouveau script : `fastapi/scripts/weekly_feedback_report.py`.

## 21.1 Correction d'un fait supposé par taches.txt

**`audit.agent_actions` et `feedback.response_ratings` ne sont pas à 0 ligne**,
contrairement à ce qu'affirmait `docs/taches.txt` ("tous deux à 0 ligne
aujourd'hui"). En réalité, au moment de l'exécution de ce script :

| Table | Lignes | Période couverte |
|---|---:|---|
| `audit.agent_actions` (domain='faq') | 861 (521 `not_found` + 340 `served`) | 2026-07-17 → 2026-07-23 |
| `feedback.response_ratings` (interaction_type='faq') | ~340 | 2026-07-14 → 2026-07-22 |

Écart expliqué : ces tables ont commencé à être peuplées à des dates
différentes (`response_ratings` dès le 14/07, `agent_actions` seulement à
partir du 17/07 — la migration 0006 est manifestement postérieure à la 0003),
et une activité de test/usage réelle s'est accumulée entre la rédaction de
`taches.txt` et cette session. Le script fonctionne donc **immédiatement sur
de la donnée réelle**, pas seulement en préparation d'un usage futur.

## 21.2 Questions sans réponse FAQ trouvée (extrait réel, top 15 toutes dates)

```
  3x  modifier
  2x  bonjour comment allez vous ?
  2x  bonjour, comment activer mon compte, merci d'avance.
  2x  cmen activé le controle parental svp
  2x  comment activer mon compte mrc / stp / 🙏 (3 variantes)
  2x  comment ca marche le parrainage
  2x  comment ca marche les cadeaux entre utilisateurs
  2x  comment desactiver les notifications
  2x  comment fonctionne le parrainage mrc / stp
```

Deux catégories de signal distinctes :

1. **Vrais trous de catalogue** : "parrainage" (programme de parrainage) et
   "désactiver les notifications" n'ont **aucune entrée correspondante**
   dans les 26 lignes réelles de `core.faq_items` (voir
   `fastapi/seeds/faq_items.sql`) — candidats directs à de nouvelles FAQ, pas
   seulement à de nouveaux exemples `ask_faq`.
2. **Message court/elliptique** ("modifier", 3 occurrences) : confirme en
   conditions réelles la faille déjà mesurée en
   [16.5](16-audit-faq-nlu-2026-07.md#165-failles-identifiées-classées-par-impact) #6
   — un mot seul, sans contexte, ne peut statistiquement pas être bien
   tranché par une recherche sur l'embedding complet d'une phrase.

## 21.3 Réponses notées « pas utile »

Sur les 15 dernières lignes réelles, une seule a pu être reliée à un score de
similarité retrouvé (0,860, "c'est quoi les lives privés payants") — les 14
autres affichent `score=introuvable`. Ce n'est pas un bug du script : la
jointure entre les deux tables reste **heuristique** (aucune clé étrangère,
convention déjà actée pour ce projet — voir
[15.1](15-modele-donnees.md)), et la fenêtre temporelle des deux tables ne se
recouvre que partiellement (voir 21.1) — une bonne partie des notations
antérieures au 17/07 n'ont simplement **aucune trace `agent_actions`
correspondante à retrouver**, la journalisation n'existant pas encore à cette
date.

Signal notable malgré tout : "Comment un créateur peut-il gagner de l'argent
sur la plateforme ?" et "Comment fonctionne le programme de récompenses ?"
apparaissent chacune 4 fois parmi les réponses jugées "pas utile" récentes —
deux FAQ du catalogue réel notées de façon répétée comme insatisfaisantes,
un candidat concret à une révision de contenu (pas un problème de recherche,
la question est bien trouvée).

## 21.4 Limites reconnues

- Jointure `response_ratings` ↔ `agent_actions` par égalité de texte
  (normalisé en minuscule/trim), pas par identifiant partagé — un score
  "introuvable" ne veut pas dire "aucune recherche n'a eu lieu", seulement
  "aucune n'a pu être retrouvée avec cette méthode".
- Regroupement des questions sans réponse par texte normalisé simple (pas de
  clustering sémantique) — "comment activer mon compte mrc"/"stp"/"🙏" restent
  comptés comme 3 questions distinctes alors qu'elles portent sur le même
  sujet ; un futur raffinement pourrait les regrouper par similarité
  d'embedding plutôt que par égalité de texte.
- Pas encore automatisé/planifié (pas de cron ni de job CI) — exécution
  manuelle à la demande pour l'instant.

---

Suite : [22. Rapport final de session](22-rapport-final-session.md)
