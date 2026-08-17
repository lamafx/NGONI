← [9. Réclamations — le formulaire](09-action-reclamation-formulaire.md) | → [11. Feedback, suggestions, notations](11-action-feedback.md)

# 10. FAQ — recherche sémantique

> **Rôle de ce document** : les deux façons d'obtenir une réponse FAQ
> (question libre vs parcours par catégories) et comment chaque réponse
> reste notable de façon fiable, même avec plusieurs questions en attente
> de notation.

## Deux chemins vers une réponse

1. **Question libre**, intent `ask_faq` classifié par Rasa Core avec
   confiance → `ActionFaqSearch` → `_present_faq_answer` → `POST /faq/search`
   (`FAQ_SERVICE_URL`) — recherche sémantique par embedding côté FastAPI
   (`FaqService.find_best_answer`, le même service que le raccourci direct
   décrit au [chapitre 3](03-api-chat.md#2-classification--raccourci-faq) ;
   la différence est le chemin d'arrivée : ici via Rasa Core après
   classification confiante, là-bas un court-circuit FastAPI quel que soit
   le moteur NLU choisi).
2. **Parcours par catégories** (boutons) : `ActionBrowseFaq` (intent
   `browse_faq`, déclenché par ex. "montre-moi des questions fréquentes")
   affiche les catégories ; `ActionSelectFaqCategory` (bouton catégorie)
   tire `GET /faq/suggestions` et affiche des boutons de questions ;
   `ActionSelectFaqQuestion` (bouton question) affiche la réponse **déjà en
   cache** (`faq_suggestions_cache`) — pas un second appel réseau, pour ne
   jamais donner un tirage différent de celui affiché dans les boutons.

Les libellés de catégorie affichés (`FAQ_CATEGORY_LABELS`, ex.
"Vérification d'identité (KYC)", "Portefeuille") sont des traductions
françaises des valeurs de `core.FaqCategory` côté FastAPI — jamais les noms
d'enum bruts.

## Une seule présentation, deux provenances (`_present_answer`)

Que la réponse vienne d'une recherche sémantique ou du cache de catégorie,
la présentation à l'utilisateur est **strictement identique** :
réponse + question de notation ("Cette réponse vous a-t-elle été utile ?")
dans un seul message, avec deux boutons 👍/👎.

**Notations multiples en attente, sans collision** : chaque réponse reçoit
une référence courte (`rating_ref`, 8 caractères hex) encodée dans le
payload de ses propres boutons, stockée dans un dict `pending_ratings`
**fusionné** (jamais écrasé) à chaque nouvelle réponse.

> Avant ce mécanisme, `question`/`answer` étaient mémorisés dans des slots
> **uniques**, écrasés par la réponse FAQ suivante si l'utilisateur ne
> notait pas la première avant d'en demander une seconde — cliquer un
> bouton "périmé" notait alors silencieusement la **mauvaise** réponse.
> Voir [11. Feedback](11-action-feedback.md) pour `ActionRecordResponseRating`,
> qui consomme ce `rating_ref`.

## Détection de message composite

`_has_composite_incident_signal` : si une question FAQ générale
("Comment fonctionne le retrait ?") apparaît dans le même message qu'un
signal d'incident concret (mot-clé d'urgence, ou "depuis 3 jours"/"depuis
2 semaines"), une proposition d'ouvrir une réclamation est ajoutée **en
plus** de la réponse FAQ — jamais un arbitrage silencieux entre les deux
interprétations possibles.

## Ce que ce chapitre ne couvre pas

L'enregistrement effectif d'une notation (`ActionRecordResponseRating`) est
au [chapitre 11](11-action-feedback.md) ; l'audit de chaque recherche FAQ
(`audit.agent_actions`, domaine `faq`) est au
[chapitre 16](16-domaines-admin-complaints-feedback-audit.md).
