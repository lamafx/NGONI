← [1. Le frontend envoie le message](01-frontend-chat-controller.md) | → [3. `POST /api/chat`](03-api-chat.md)

# 2. `POST /api/parse`

> **Rôle de ce document** : ce que fait précisément cet endpoint, et ce
> qu'il ne fait jamais (il ne produit aucune réponse de conversation, voir
> chapitre 3 pour ça).

## Ce que fait cet endpoint

`fastapi/app/main.py::parse_message` est une **classification pure**, sans
aucun effet sur l'état de la conversation. Deux cas :

1. **Payload structuré** (le texte commence par `/`, voir
   [1. Le frontend envoie le message](01-frontend-chat-controller.md)) :
   contourne entièrement le sélecteur de modèle et interroge Rasa
   directement (`call_rasa_with_retry(RASA_PARSE_URL, {"text": text})`) —
   c'est déjà une intention pré-classifiée côté frontend, il n'y a rien à
   déduire.
2. **Texte libre** : délègue à `app/domains/nlu/engines.py::predict(model_id, text)`,
   le point d'entrée unique décrit au [chapitre 4](04-selecteur-moteur-nlu.md).

Réponse dans les deux cas :

```json
{
  "text": "...",
  "intent": { "name": "...", "confidence": 0.0 },
  "entities": [...]
}
```

## Bornes appliquées

`ParseRequest` (Pydantic) impose `text` entre 1 et 4000 caractères — même
plafond que `ChatRequest` (chapitre 3), pensé pour laisser une marge
confortable au-dessus du plus grand champ libre réellement validé plus loin
dans le flux (description de réclamation, 2000 caractères max côté
`rasa/actions/reclamation.py`), tout en bornant la requête dès l'entrée du
système plutôt qu'une fois arrivée dans un formulaire.

## Ce que cet endpoint NE fait jamais

- Il n'appelle jamais le webhook Rasa (`/webhooks/rest/webhook`) — seulement
  `/model/parse`, qui ne déclenche aucune action ni formulaire.
- Il n'écrit jamais en base de données.
- Une panne de cet endpoint n'interrompt jamais la conversation réelle :
  seule la bannière d'intention/confiance reste vide côté frontend.
