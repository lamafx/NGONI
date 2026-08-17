← [Index](00-index.md) | → [2. `POST /api/parse`](02-api-parse.md)

# 1. Le frontend envoie le message

> **Rôle de ce document** : décrire précisément ce qui se passe côté
> navigateur entre l'appui sur "Envoyer" et la réception d'une réponse —
> rien côté serveur n'est traité ici (voir chapitres 2 et 3).

## Deux appels, jamais un seul

`frontend/pages/chat/chat.controller.js::handleOutgoing` déclenche **deux
appels HTTP séquentiels** à chaque message :

1. `POST /api/parse { text, model }` — uniquement pour **afficher**
   l'intention détectée et sa confiance dans la bannière au-dessus du champ
   de saisie (`#parse-info`, géré par `chat-view.js::updateParseInfo`).
   N'affecte jamais la conversation elle-même : si cet appel échouait, la
   conversation continuerait normalement, seule la bannière resterait vide.
2. `POST /api/chat { text, user_id, model, superagent }` — la vraie requête,
   celle qui produit la réponse du bot (détail : [3. `POST /api/chat`](03-api-chat.md)).

## D'où viennent `model` et `superagent`

- `model` vient du sélecteur "Moteur actif" en haut de l'écran
  (`model.store.js`), peuplé au chargement de la page par `GET /api/models`.
  Par défaut : Rasa (DIETClassifier). Voir
  [4. Le sélecteur de moteur NLU](04-selecteur-moteur-nlu.md) pour ce que
  ce choix change réellement.
- `superagent` vient du bouton "🔓 Mode Super-Agent" (`superagent.store.js`),
  **désactivé à chaque rechargement de page** — jamais coché silencieusement
  par un choix précédent, décision explicite du code.

## Le cas des boutons cliqués

Si le texte envoyé commence par `/` (ex. `/select_faq_question{"faq_slug": "..."}`),
c'est qu'un bouton de suggestion a été cliqué plutôt qu'un texte tapé au
clavier (`chat-view.js::addButtons`). Le payload technique part vers le
serveur, mais le **titre lisible du bouton** est ce qui s'affiche dans la
bulle utilisateur — jamais le payload brut. Un clic suit alors exactement le
même chemin qu'une saisie clavier (`/api/parse` puis `/api/chat`), sans
logique dupliquée ; côté serveur, ce payload structuré court-circuite
entièrement le sélecteur de modèle (voir chapitres 2 et 3).

## Après la réponse

`chat.controller.js` reçoit `{ messages: [...] }` et les affiche un par un
dans `#messages`. S'il y a plusieurs messages dans un même tour (ex. une
confirmation suivie d'une relance contextuelle), une pause avec indicateur
de frappe ("Ngoni écrit…") sépare chacun — pour qu'ils se lisent comme des
pensées distinctes plutôt qu'un seul pavé de texte (détail :
[17. Retour jusqu'à l'utilisateur](17-retour-reponse-utilisateur.md)).

L'historique de conversation (`history.store.js`) est persisté en
`localStorage`, par onglet/navigateur — jamais côté serveur pour le
frontend lui-même (le tracker Rasa, lui, persiste côté serveur, voir
[6. Rasa Core](06-rasa-core-policies-domain.md)).
