# 19. Prise en charge humaine (escalade, file conseiller, supervision)

> Ajouté le 2026-09-16. Couvre les cas d'utilisation « Escalader vers un
> agent humain », « Prendre en charge une demande », « Prendre en charge une
> réclamation » et les compléments de « Administrer le système du support
> client ». L'authentification (« S'authentifier ») reste hors périmètre —
> voir [13. Limitations](13-limitations.md) §13.1.

## 19.1 Ce que ce chapitre ajoute au flux existant

Jusqu'ici, « escalader » voulait dire **créer un ticket** : le dossier était
bien enregistré, mais aucune personne ne le recevait, aucune conversation
n'était reprise, et rien ne permettait à un conseiller de lire ce que
l'usager avait dit. L'historique de dialogue vivait uniquement dans le
tracker interne de Rasa, qui n'est exposé par aucune API.

Trois tables et deux surfaces d'API comblent cet écart :

| Table (`ia.`) | Rôle |
|---|---|
| `conversations` | Une ligne par conversation : statut, escalade, conseiller assigné, ticket lié, dernière intention |
| `conversation_messages` | Chaque message (`user` / `bot` / `agent`), avec l'intention et la confiance pour les messages d'usager |
| `support_agents` | Les conseillers à qui une conversation ou un ticket peut être attribué |

Migration : `fastapi/migrations/0016_conversations_supervision.sql`
(+ `fastapi/seeds/support_agents.sql` pour trois conseillers de
développement).

## 19.2 Cycle de vie d'une conversation

```
BOT ──escalade──► ESCALADE_DEMANDEE ──assignation──► PRISE_EN_CHARGE ──clôture──► RESOLUE
 ▲                                                                                   │
 └──────────────────── nouveau message de l'usager ─────────────────────────────────┘
```

Deux règles portent tout le reste :

1. **`ESCALADE_DEMANDEE` ne coupe pas l'assistant.** Tant que personne n'a
   repris la main, le bot continue de répondre — laisser l'usager sans
   aucune réponse parce qu'il a demandé un humain serait pire que la
   situation d'avant.
2. **`PRISE_EN_CHARGE` fait taire le bot** (`ConversationService.is_muted`).
   Sans ce silence, l'usager recevrait deux réponses concurrentes au même
   message, celle du conseiller et celle de Rasa.

Le silence est appliqué **côté FastAPI**, jamais côté Rasa : `POST /api/chat`
refuse de relayer au webhook, et les clients qui parlent directement à Rasa
lisent le drapeau `handoff` renvoyé par `POST /conversations/turns`. Le
mécanisme de prise en charge lui-même ne touche donc ni le modèle NLU, ni
`domain.yml`, ni `rules.yml`.

### 19.2.1 La seule addition côté Rasa : annuler sa demande

« Finalement je n'ai plus besoin d'un conseiller » demande de **comprendre
une phrase** — ça, aucun endpoint ne peut le faire à la place du NLU. D'où :

| Élément | Fichier |
|---|---|
| Intention `cancel_human_agent_request` (15 exemples) | `rasa/data/nlu.yml` |
| Déclaration intention + action | `rasa/domain.yml` |
| 3 règles (normale, diagnostic en attente, formulaire actif) | `rasa/data/rules.yml` |
| `action_cancel_human_agent_request` | `rasa/actions/handoff.py` |
| `POST /conversations/withdraw` | `domains/conversations/router.py` |

Point de vigilance assumé, documenté dans `nlu.yml` : « laisse tomber » ou
« finalement non » **tout seuls** appartiennent à `deny` (refus d'une
proposition en cours, ex. pendant le formulaire de réclamation). Les cinq
premiers exemples — les seuls qui entrent dans l'invite few-shot du
classifieur, voir `examples_per_intent` dans `config.yml` — mentionnent donc
tous explicitement le conseiller ou la mise en relation. Mieux vaut qu'un
refus ambigu reste classé `deny` (comportement actuel, inchangé) que de voir
une escalade annulée sur une phrase qui ne parlait pas d'elle.

L'action n'annonce jamais une annulation qu'elle n'a pas obtenue : si le
moteur ne répond pas, elle le dit ; si un conseiller a **déjà pris** le
dossier, elle refuse de l'effacer de sa file dans son dos et l'explique à
l'usager.

> **Réentraînement obligatoire** avant que cette intention soit reconnue :
> `docker compose run --rm rasa train`, puis redémarrage de `rasa` et
> `actions` (procédure standard, voir [10. Déploiement](10-deploiement.md)).
> Tout le reste de ce chapitre fonctionne sans réentraîner quoi que ce soit.

## 19.3 Qui écrit l'historique

Deux chemins, selon le client :

| Client | Chemin | Journalisation |
|---|---|---|
| Un client qui passe par le moteur | `POST /api/chat` | Automatique, côté serveur (message d'usager + intention + réponses du bot) |
| L'interface React, qui interroge Rasa directement (`frontend/src/services/rasaClient.js`) | webhook Rasa | `POST /conversations/turns`, appelé après coup par `chatService.js` |

La seconde route existe parce que le tracker de Rasa n'est pas exposé et que
le conseiller a besoin de l'historique. Elle est déclarative, comme le reste
de cette API sans authentification : elle alimente l'affichage du conseiller
et la volumétrie, **jamais une décision automatique**.

Effet de bord utile : `conversation_messages.intent` est la télémétrie
d'intentions qui manquait pour `/admin/dashboard/intent-distribution` (voir
`api_admin_a_developper.md` §3, « aucune donnée n'existe pour calculer
ceci »).

## 19.4 Routes

### Côté usager (non protégées, comme le reste du périmètre client)

| Méthode | Chemin | Objet |
|---|---|---|
| POST | `/conversations/escalate` | Demander un conseiller (bouton de l'interface, pas une phrase à classer) |
| POST | `/conversations/turns` | Journaliser un tour, pour les clients qui parlent directement à Rasa |
| POST | `/conversations/withdraw` | Retirer une demande de conseiller encore en attente |
| GET | `/conversations/{id}/updates?after=` | Récupérer les réponses du conseiller (interrogation périodique) |

`updates` ne renvoie jamais les messages de l'usager lui-même : ils sont déjà
affichés chez lui.

### Côté conseiller / administration (`X-Internal-Secret` obligatoire)

| Méthode | Chemin | Objet |
|---|---|---|
| GET | `/admin/conversations/` | La file (`status`, `assigned_to`, `escalated`, `unassigned`) |
| GET | `/admin/conversations/{id}` | Le fil complet |
| GET | `/admin/conversations/{id}/context` | Résumé de reprise : intentions vues, diagnostic tenté, tickets liés, chronologie |
| POST | `/admin/conversations/{id}/assign` | **Prendre en charge une demande** (409 si un autre conseiller la tient, `?force=true` pour reprendre) |
| POST | `/admin/conversations/{id}/messages` | Répondre (409 tant que la conversation n'est pas prise en charge) |
| POST | `/admin/conversations/{id}/resolve` | Clore et rendre la main au bot |
| POST | `/admin/complaints/{ticket_id}/assign` | **Prendre en charge une réclamation** (attribue + passe en `IN_PROGRESS`) |
| GET/POST | `/admin/agents/` | Annuaire des conseillers |
| PATCH | `/admin/agents/{id}/status` | Statut déclaré (`online`/`away`/`offline`) |
| GET | `/admin/dashboard/summary` | KPI + variation période sur période |
| GET | `/admin/dashboard/conversation-volume` | Série journalière |
| GET | `/admin/dashboard/intent-distribution` | Répartition réelle des intentions |
| GET | `/admin/dashboard/recent-activity` | Flux d'événements reconstitué depuis les traces |
| GET | `/admin/diagnostics/runs` | Diagnostics exécutés + latence (lecture sur `diagnostic_audit_log`) |
| GET | `/admin/system/health` | Sonde réelle : PostgreSQL, Rasa, chaque service de `services_registry.yaml` |
| GET | `/admin/users/` | Usagers vus par le support (agrégation, aucune table créée) |
| GET | `/admin/users/{user_id}` | Historique conversations + tickets d'un usager |

Le statut d'un conseiller est **dérivé** de son activité
(`PRESENCE_TIMEOUT_MINUTES = 15`) et pas seulement déclaré : personne ne
pense à se déclarer absent en partant.

## 19.5 Interfaces

- `frontend/src/pages/AgentLivePage.jsx` (`/agent/live`) : le poste conseiller
  sur données réelles — file, prise en charge, réponse, clôture, dossier de
  reprise. `AgentPage.jsx` (`/agent`) reste la scène rejouée de la
  démonstration, inchangée.
- `frontend/src/pages/ChatPage.jsx` : le bouton « Contactez un conseiller »
  escalade réellement, et la page récupère les réponses humaines par
  interrogation périodique.
- `frontend/src/pages/AdminPage.jsx` : hors démonstration, le tableau des
  tickets, la répartition des intentions, les conseillers en ligne, l'état
  des services et les KPI viennent tous du moteur ; l'action « Prendre en
  charge » écrit réellement. En mode démonstration, la page continue de
  rejouer le scénario de `mockData.js` — les deux sources ne sont jamais
  mélangées, et aucun repli silencieux de l'une vers l'autre n'existe : si
  le moteur ne répond pas hors démonstration, la page le dit au lieu
  d'afficher des chiffres crédibles et faux.
- `frontend/src/pages/AdminUsersPage.jsx` (`/admin/utilisateurs`) : l'entrée
  de navigation « Utilisateurs », jusque-là inerte.

Interrogation périodique et non WebSocket : le moteur n'a aucune
infrastructure temps réel (ni broker, ni connexions persistantes), et en
déployer une pour ce seul usage ne se justifie pas à l'échelle visée.

## 19.6 Usagers (`/admin/users`)

Agrégation en lecture seule sur `ia.conversations` et `ia.complaints` —
**aucune table d'utilisateurs n'est créée**, volontairement : les profils
appartiennent à `ngoni-user-service` (voir [3. Taxonomie](03-taxonomie.md)),
et les dupliquer ici ferait diverger deux bases dès la première modification
de profil. Sont donc renvoyés l'identifiant de contact, le volume
d'échanges, les tickets et la dernière activité — jamais un nom ou un email
inventé. Page : `frontend/src/pages/AdminUsersPage.jsx` (`/admin/utilisateurs`).

## 19.7 Ce qui reste ouvert

- **Authentification** (`/admin/auth/*`) : exclue du périmètre. Le secret
  partagé `X-Internal-Secret` protège les routes, mais rien n'identifie
  *quel* conseiller agit : `agent_id` est déclaré par le poste
  (`VITE_AGENT_ID`), pas prouvé. Tout le reste en dépend : tant qu'il n'y a
  pas d'identité, « prendre en charge » reste déclaratif.
- **Temps réel** : pas de notification poussée. La pastille de la cloche
  compte les tickets ouverts et les conversations en attente (`GET
  /admin/dashboard/summary`), mais un conseiller doit regarder sa file — le
  rafraîchissement est périodique, pas événementiel.
- **Profils usagers** : voir §19.6 — enrichissement possible le jour où
  `ngoni-user-service` est joignable, sous forme de proxy.

## Tests

- `fastapi/tests/test_conversations_handoff.py` — règles métier contre une
  vraie base (statuts, contexte, temps de réponse moyen, présence).
- `fastapi/tests/test_conversations_api.py` — parcours HTTP complet, et
  vérification que les routes `/admin/*` refusent sans le secret.

Les deux sont ignorés (`skip`) si PostgreSQL n'est pas joignable.
