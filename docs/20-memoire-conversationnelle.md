# 20. Mémoire conversationnelle et qualité de compréhension

> Ajouté le 2026-10-21. Couvre ce qui permet à l'assistant de **suivre une
> discussion** : comprendre un message à partir de ce qui précède, se
> souvenir d'une conversation précédente, répondre naturellement quand il ne
> peut pas aider, et la mise au point du classifieur d'intention qui rend
> tout cela possible.

## 20.1 Principe : la tâche aux règles, la conversation au LLM

L'assistant combine deux mécanismes, chacun là où il est fiable :

| Situation | Qui décide | Pourquoi |
|---|---|---|
| Une tâche attend une valeur précise (champ de `reclamation_form`, précision demandée par le diagnostic) | La machine à états Rasa (formulaire, règles, `pending_field`) | Elle sait exactement ce qu'elle attend ; ses règles sont réglées sur la classification **sans** contexte (ex. une réponse classée `plainte` est rejetée par le mapping de `category`) |
| Entre les tâches : suite d'une question, « oui » après une proposition, discussion libre | Le classifieur Qwen, **avec** le contexte de la conversation | C'est là qu'un message isolé est ambigu (« et sur Android ? », « oui ») |

Le contexte n'est donc **jamais** injecté pendant qu'une tâche attend une
valeur (voir `_task_is_waiting`, `rasa/components/qwen_intent_classifier.py`),
ni pour un message long et autonome (`_is_elliptic`). Il est en outre
**désactivé par défaut**, voir [20.4](#204-interrupteurs).

Ce qui suit **reste actif sans LLM supplémentaire** :

- **Suite de question FAQ** : « et combien de temps ça prend ? » après « Comment retirer mes revenus ? ». La recherche combine les deux questions (`standalone_question`, `rasa/actions/common.py`), uniquement pour une tournure de suite évidente (« et… », « pour… », « sur… », « depuis… »).
- **« oui » à une demande de valeur** dans le diagnostic (« Avez-vous une référence ? ») : l'agent répond « Parfait, pouvez-vous me l'indiquer ? » au lieu de « Ce format ne semble pas correct » (`_is_bare_affirmation`, `rasa/actions/diagnostic.py`).
- **Mémoire entre conversations** (20.2) : une simple lecture en base, environ 0 s de plus.

## 20.2 Trois niveaux de mémoire

```
Message de l'utilisateur (frontend)
   │  1. lit le tracker Rasa (GET /conversations/{id}/tracker) : quelques ms
   │  2. envoie metadata = { user_id, dialogue_context: {turns, slots, active_loop} }
   ▼
Classifieur Qwen ── contexte inséré APRÈS le préfixe fixe du prompt
   │                (le cache KV d'Ollama continue de servir)
   │  → intention + entités + "reformulation" autonome si le message
   │    ne se comprend qu'avec le contexte
   ▼
Actions Rasa
   ├─ FAQ : cherche la reformulation ("et sur Android ?" →
   │        "Comment recharger mon portefeuille sur Android ?")
   ├─ Accueil : GET /conversations/memory → rappelle le dernier sujet
   │            et le statut ACTUEL du ticket qui en est né
   └─ Repli / hors-sujet : réponse générée avec le fil de la conversation
```

| Niveau | Contenu | Source | Durée de vie |
|---|---|---|---|
| État de la tâche | Montant, plateforme, date, catégorie… déjà donnés | Slots du tracker Rasa | La conversation |
| Fil récent | Les 4 derniers échanges (2 allers-retours) | Événements du tracker Rasa | La conversation |
| Conversations précédentes | Dernier sujet réel + ticket et son statut | Tables `conversations`, `conversation_messages`, `complaints` | 30 jours |

### Identité stable

L'identifiant de conversation Rasa (`sender`) change volontairement à chaque
rechargement de page (tracker neuf, voir `rasaSenderId` dans
`frontend/src/services/chatService.js`). La mémoire entre conversations
repose donc sur un **`user_id` stable**, conservé dans le navigateur
(`localStorage`, clé `ngoni-user-id`) faute d'authentification
([13.1](13-limitations.md)). Il est envoyé dans `metadata.user_id` et
journalisé dans `conversations.user_id`.

Le `user_id` d'un **ticket** reste l'identifiant de conversation : c'est la
clé de la file des conseillers ([19](19-prise-en-charge-humaine.md)), il ne
faut pas le changer.

## 20.3 Mise au point du classifieur

Mesures sur des phrases réalistes **absentes de `nlu.yml`**, via
`POST /model/parse` (message seul, sans contexte) :

| Jeu de phrases | Avant (2026-10-21) | Après |
|---|---|---|
| Jeu 1 : 48 phrases, utilisé pendant la mise au point | 29/48 = **60 %** | 39/48 = 81 % |
| Jeu 2 : 24 phrases, écrit avant les dernières corrections | — | 17/24 = 71 % (avant les noms explicites) |
| **Jeu 3 : 25 phrases jamais vues pendant la mise au point** | — | **20/25 = 80 %** |

Le chiffre honnête à retenir est celui du **jeu 3 (80 %)**. Le jeu 1 a servi
à corriger les définitions, son score est donc optimiste.

Par catégorie (jeu 1, avant → après) : diagnostic 4/6 → 6/6, FAQ 1/8 → 4/8
avant les noms explicites (les 6 questions FAQ en échec passent ensuite
toutes), hors-sujet 0/4 → 1/4.

Temps de réponse sans GPU (classification seule) : 10 à 17 s par message,
environ 20 s pour un message de diagnostic porteur d'entités.

Ce qui a changé, et pourquoi :

| Changement | Problème constaté |
|---|---|
| Une **définition** par intention (`INTENT_DESCRIPTIONS`) | Avec 5 exemples seulement, le modèle classait par ressemblance de surface : « Comment recharger mon portefeuille ? » → `request_human_agent`, toujours à 0,95 |
| Exemples **répartis** sur toute la liste, 8 au lieu de 5 (`train()`) | Les 5 premiers d'`ask_faq` parlaient tous de création de compte ; ceux d'`out_of_scope` étaient des phrases de réponse du bot |
| **Noms explicites** présentés au modèle (`PROMPT_LABELS`) : `question_sur_ngoni`, `competences_de_l_assistant`, `hors_sujet`… | Un modèle de 1,7B se fie au nom de l'étiquette : `ask_capabilities` attirait « est-ce que je peux… » |
| JSON sur **une seule ligne**, au plus 2 intentions classées | Sans GPU, la génération tourne à environ 3 tokens/s ; un JSON indenté coûtait 86 tokens (26 s) au lieu de 51 |
| Entités **vérifiées dans le texte** (`_squash`) | Le modèle inventait des valeurs (`"platform": "mobile"` absent du message) |
| `num_ctx` fixé à 6144 (`OLLAMA_NUM_CTX`), identique partout | Prompt fixe d'environ 3300 tokens + contexte + réponse : au-delà de 4096 (défaut d'Ollama), le **début** du prompt est tronqué sans erreur |

Le panneau « Sous le capot » ne fait plus sa propre classification avant
l'envoi : il lit l'intention **réellement** retenue dans le tracker après la
réponse. Cela supprime un appel complet au LLM par message, et le panneau
affiche enfin ce qui a piloté la réponse, contexte compris.

## 20.4 Interrupteurs

Chaque mécanisme se coupe sans toucher au code, puis on redémarre le conteneur concerné :

| Variable | Fichier | Défaut | Rôle |
|---|---|---|---|
| `NLU_CONTEXT_ENABLED` | `rasa/.env` | **`false`** | Contexte de la conversation dans le classifieur |
| `NLU_CONTEXT_MAX_TURNS` | `rasa/.env` | 4 | Taille du fil récent |
| `LLM_REPLY_ENABLED` | `rasa/actions/.env` | **`false`** | Réponse de repli générée (sinon textes fixes `utter_default` / `utter_out_of_scope`) |
| `OLLAMA_NUM_CTX` | les deux | 6144 | Doit rester identique dans les deux fichiers |

**Pourquoi les deux fonctions LLM sont désactivées par défaut** (mesures sans
GPU, 2026-10-21) :

| Fonction | Sans | Avec |
|---|---|---|
| Contexte dans le classifieur (« et combien de temps ça prend ? » après une question FAQ) | 16 à 17 s, `question_sur_ngoni` ✅ | 36 à 43 s, `diagnostic` + entités inventées ❌ |
| Réponse de repli générée (« qui va gagner la CAN ? ») | Texte fixe, environ 15 s | Réponse naturelle et juste, mais **48 s** au total |

Un modèle de 1,7B sur processeur tire plus de confusion que d'aide de
l'historique, et la génération tourne à environ 3 tokens/s. Les deux
fonctions sont prêtes à être réactivées avec un GPU ou un modèle plus grand.
Les suites de question FAQ restent gérées **sans** LLM (voir 20.2).

L'accueil avec mémoire ne s'active que si un `user_id` est reçu. Sans lui,
l'accueil reste celui d'avant.

## 20.5 Garde-fous

- **Réponse générée** : deux phrases maximum. Elle est rejetée si elle contient un chiffre, un lien ou une adresse, si elle dépasse 320 caractères ou si elle arrive après le délai. Le texte fixe est alors servi.
- **Mémoire** : uniquement ce qui a été réellement dit (message dont l'intention porte un sujet : diagnostic, réclamation, plainte, FAQ, suggestion) ou créé (ticket, avec son statut **actuel** lu en base). Une conversation sans sujet (« bonjour » seul) est ignorée.
- **Reformulation** : acceptée seulement si un contexte a été fourni, et si elle diffère du message.

## 20.6 Limites connues

- **Latence** : 10 à 20 s par message sans GPU. Le préfixe fixe du prompt (environ 3300 tokens) n'est pas réutilisé de façon fiable par le cache d'Ollama sur cette machine.
- **Hors-sujet** encore mal reconnu (1/4 sur le jeu 1) : souvent pris pour `bot_challenge`, dont la réponse (« je suis l'assistant virtuel NGONI… ») reste toutefois acceptable.
- **FAQ** : la recherche par embeddings sert parfois une mauvaise réponse avec assurance quand le sujet n'existe pas au catalogue. Exemple : « Comment recharger mon portefeuille ? » renvoie la réinitialisation du mot de passe (score 0,676, seuil 0,57 calibré sur seulement 9 paires). Remède : ajouter l'entrée au catalogue, puis recalibrer le seuil sur un vrai corpus.
- **Confiance** : le LLM déclare presque toujours 0,95. Ce n'est pas une probabilité, et le repli « je n'ai pas compris » se déclenche donc rarement.
- **Mémoire** : liée au navigateur (`localStorage`). Un autre navigateur ou une navigation privée, c'est un nouvel utilisateur. Une vraie authentification lèverait cette limite ([13.1](13-limitations.md)).
