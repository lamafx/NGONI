← [16. Les domaines simples derrière l'admin](16-domaines-admin-complaints-feedback-audit.md) | → [18. Le modèle d'embeddings partagé](18-modele-embeddings-partage.md)

# 17. Retour jusqu'à l'utilisateur

> **Rôle de ce document** : le chemin inverse — de la réponse générée par
> une action Rasa (chapitres 7 à 11) jusqu'à son affichage réel dans le
> navigateur. Rien sur la génération de cette réponse elle-même ici.

## Rasa → FastAPI → frontend, sans transformation

Une action Rasa (`dispatcher.utter_message(text=..., buttons=...)`)
produit un ou plusieurs messages, collectés par `CollectingDispatcher` et
renvoyés par le webhook REST comme un tableau JSON
(`[{text, buttons}, ...]`). `fastapi/app/main.py::send_to_bot`
([chapitre 3](03-api-chat.md)) retransmet ce tableau **tel quel** :
`{"messages": rasa_response.json()}` — FastAPI ne réinterprète, ne
reformate et ne filtre jamais son contenu.

## Côté frontend (`chat.controller.js::handleOutgoing`)

```
messages.length === 0        -> "Aucune réponse reçue du bot."
messages.length >= 1          -> chaque message affiché l'un après l'autre
```

Pour le **2ᵉ message d'un même tour et les suivants** (ex. une confirmation
suivie d'une relance contextuelle), une pause avec indicateur de frappe
("Ngoni écrit…", `view.showTyping()`) précède son affichage — durée
`MULTI_MESSAGE_PAUSE_MS` (`config/constants.js`). Sans cette pause, plusieurs
messages d'un même tour s'affichaient d'un coup comme un seul pavé de
texte ; trouvé par audit UX (2026-07) que les séparer ainsi les fait lire
comme des pensées distinctes.

Chaque message est persisté dans l'historique local
(`historyStore.appendMessage`, `localStorage` par onglet) **avant**
d'être affiché — un rechargement de page retrouve donc la conversation
telle quelle.

## Les boutons suivent le même chemin qu'une saisie clavier

`view.addBotMessage(text, buttons, handleOutgoing)` : si le message porte
des `buttons` (ex. suggestions FAQ, choix de catégorie), chaque bouton
cliqué rappelle `handleOutgoing(payload, displayText)` — **exactement la
même fonction** qu'une saisie clavier. Le payload technique
(`/select_faq_question{"faq_slug": "..."}`) part au serveur ; le titre
lisible du bouton ("Vérification d'identité (KYC)") s'affiche dans la
bulle utilisateur. Voir [1. Le frontend envoie le message](01-frontend-chat-controller.md)
pour ce court-circuit vu côté envoi.

## En cas d'erreur

Une exception (timeout, `HTTPException 502` de FastAPI, etc.) pendant
`handleOutgoing` retire l'indicateur de frappe, affiche un message
générique ("Désolé, une erreur est survenue...") **côté utilisateur**, et
journalise le détail technique complet uniquement dans la console
navigateur — jamais dans la bulle de conversation elle-même (constaté en
pratique : un message de plus de 4000 caractères, déjà borné côté serveur,
s'affichait auparavant intégralement, texte original inclus, en cas de
dépassement).

## Ce que ce chapitre ne couvre pas

L'admin dashboard a son propre chemin de rendu (composants JS statiques
`createEl`, pas de framework) — voir
[16. Domaines admin](16-domaines-admin-complaints-feedback-audit.md) pour
ce qu'il affiche et [[project-ngoni-ia-service-frontend]] pour son
architecture visuelle.
