← [10. FAQ — recherche sémantique](10-action-faq.md) | → [12. Résilience côté serveur Actions](12-resilience-actions-server.md)

# 11. Feedback, suggestions, notations

> **Rôle de ce document** : les trois actions qui écrivent dans
> `feedback.entries` et, pour deux d'entre elles, créent aussi un ticket de
> suivi — le pont entre une intention de l'utilisateur (`suggestion`,
> `plainte`, notation d'une réponse) et sa trace persistée.

## Suggestions (`ActionStoreSuggestion`, intent `suggestion`)

Remplace un ancien appel direct à `utter_thanks_for_suggestion` qui
promettait une transmission à l'équipe **qui n'existait pas** — FastAPI
crée désormais réellement une entrée persistée. `POST /feedback` avec
`type: "suggestion"`. En cas de panne du service, `utter_suggestion_storage_failed`
est affiché plutôt que le message de remerciement habituel : dire "merci,
transmis" alors que rien n'a été enregistré serait trompeur.

## Plaintes (`ActionAcknowledgeComplaint`, intent `plainte`)

Chaque plainte crée **deux** choses côté FastAPI
(`FeedbackService.create_entry`, voir
[16. Domaines admin](16-domaines-admin-complaints-feedback-audit.md)) :
une entrée `feedback.entries` (trace brute) **et** un ticket de suivi
`complaints.complaints` (`created_by: "ai_feedback_ticket"`, catégorie
"Plainte", urgence "medium") — pour que le signal reste actionnable par
l'équipe support, pas seulement consultable en base. Là aussi,
`utter_complaint_storage_failed` remplace le message habituel si le service
est indisponible — symétrique à la suggestion, pour la même raison (ne
jamais laisser croire qu'une trace a été créée si ce n'est pas le cas).

## Notation d'une réponse (`ActionRecordResponseRating`)

Déclenchée par les boutons 👍/👎 affichés après une réponse FAQ (voir
[10. FAQ](10-action-faq.md#une-seule-présentation-deux-provenances-_present_answer)),
via les payloads structurés `/rate_response_useful{"rating_ref": "..."}` et
`/rate_response_not_useful{"rating_ref": "..."}`. Une seule action gère les
deux intents (`rate_response_useful`/`rate_response_not_useful`) : le
`rating_ref` du payload identifie précisément **quelle** réponse est
notée dans le dict `pending_ratings`, retiré du dict une fois la notation
enregistrée — jamais notée deux fois par erreur sur un tour ultérieur sans
rapport. `utter_rating_storage_failed` si le service est indisponible,
même principe que ci-dessus.

## Longueur maximale

`MAX_MESSAGE_LENGTH = 2000` côté `FeedbackService` (FastAPI) — alignée sur
`MAX_DESCRIPTION_LENGTH` de `reclamation.py` ([chapitre 9](09-action-reclamation-formulaire.md)),
même raisonnement : protection contre l'épuisement de ressources sur un
champ libre sans autre limite. Tronque silencieusement au-delà, jamais un
rejet.

## Ce que ce chapitre ne couvre pas

La table `feedback.entries` et son exploitation côté dashboard admin sont
au [chapitre 16](16-domaines-admin-complaints-feedback-audit.md).
