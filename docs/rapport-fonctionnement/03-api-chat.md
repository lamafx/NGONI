← [2. `POST /api/parse`](02-api-parse.md) | → [4. Le sélecteur de moteur NLU](04-selecteur-moteur-nlu.md)

# 3. `POST /api/chat`

> **Rôle de ce document** : l'endpoint qui produit réellement la réponse du
> bot — le seul des deux appels frontend qui compte pour la conversation
> elle-même.

`fastapi/app/main.py::send_to_bot` exécute, dans l'ordre :

## 1. Cas du payload structuré

Si le texte commence par `/` (bouton cliqué), passe directement à l'étape 3
ci-dessous — aucune classification à refaire.

## 2. Classification + raccourci FAQ

Sinon, appelle le même `predict()` qu'au [chapitre 2](02-api-parse.md).
**Raccourci spécifique** : si l'intention retenue est exactement `ask_faq`
(égalité stricte, pas un simple `"faq" in intent` — pour ne pas intercepter
`browse_faq`/`select_faq_category`/`select_faq_question`, qui doivent
passer par Rasa, voir [10. FAQ](10-action-faq.md)), FastAPI répond
**directement** avec la meilleure réponse FAQ trouvée par recherche
sémantique (`FaqService.find_best_answer`, exécutée dans un thread via
`run_in_threadpool` pour ne pas geler la boucle asyncio pendant
l'encodage + la requête DB synchrone), **sans jamais appeler Rasa**. Le
lookup est tracé dans `audit.agent_actions` (`record_faq_lookup`, voir
[16. Domaines admin](16-domaines-admin-complaints-feedback-audit.md)).

## 3. Relais vers Rasa

Dans tous les autres cas, le texte **brut** — jamais l'intention déjà
classifiée par le moteur choisi — part vers le webhook Rasa
(`POST /webhooks/rest/webhook`) avec :

- `sender`: `user_id` fourni ou `"frontend_user"` par défaut ;
- `message`: le texte brut ;
- `metadata: { superagent }` : seul canal utilisé pour transporter le
  signal du Mode Super-Agent jusqu'aux actions Rasa (voir
  [8. Diagnostic — exécution](08-action-diagnostic-execution.md)) —
  ni le texte ni une intention ne peuvent porter ce signal ;
- header `X-Trace-ID`: un UUID généré ici, journalisé côté FastAPI **et**
  côté Actions pour le même tour de conversation — un `grep` sur ce
  `trace_id` relie directement les deux journaux, sans reconstruction
  manuelle par timestamp.

> **Pourquoi le texte brut, jamais l'intention déjà classifiée ?** Vérifié
> empiriquement (commentaire du code, `main.py`) : injecter une intention
> synthétique à la place cassait la poursuite du formulaire de réclamation
> dès que le moteur sélectionné classifiait la réponse libre de
> l'utilisateur autrement que Rasa ne l'aurait fait lui-même. Rasa Core
> s'appuie sur sa **propre** analyse pour gérer un tour en cours
> (remplissage de slot, relance...), un besoin qu'un simple classificateur
> d'intention isolé ne couvre pas. Le moteur sélectionné par l'utilisateur
> ne pilote donc que **deux** choses dans tout le flux : l'intent affiché
> par `/api/parse`, et le raccourci `ask_faq` ci-dessus — jamais l'état
> conversationnel de Rasa Core.

## Réponse

`{"messages": rasa_response.json()}` — la réponse de Rasa est retransmise
**telle quelle**, sans transformation. Voir
[17. Retour jusqu'à l'utilisateur](17-retour-reponse-utilisateur.md) pour
ce qui se passe ensuite côté affichage.

## Bornes et robustesse

Même plafond `text` (1-4000 caractères) qu'au chapitre 2. Toute panne de
contact avec Rasa (timeout, erreur réseau) devient une `HTTPException 502`
explicite plutôt qu'une exception brute — `call_rasa_with_retry`
(`app/shared/rasa_client.py`) retente 3 fois avec un délai d'1s avant
d'abandonner.
