← [11. Feedback, suggestions, notations](11-action-feedback.md) | → [13. Diagnostic Engine — le registre](13-diagnostic-engine-registry.md)

# 12. Résilience côté serveur Actions

> **Rôle de ce document** : les mécanismes génériques de robustesse
> réutilisés par plusieurs actions (`rasa/actions/common.py`) — pas la
> logique métier elle-même (chapitres 7 à 11), seulement ce qui la protège
> des pannes réseau et de l'incompréhension répétée.

## `SimpleCircuitBreaker` (générique)

Disjoncteur en mémoire de process : ouvre après **3 échecs consécutifs**,
se referme automatiquement après **30 secondes** (pas de sonde active,
simple "half-open" implicite). Extrait du disjoncteur de tickets
([chapitre 9](09-action-reclamation-formulaire.md)) pour être réutilisé
par d'autres appels HTTP sujets à panne prolongée :

- capacités du Diagnostic Engine (`_capabilities_circuit_breaker`,
  [chapitre 7](07-action-diagnostic-classification.md)) ;
- service d'embeddings (`_embeddings_circuit_breaker`, partagé entre
  `_embed_message` et `_embed_messages` — une panne touche les deux
  identiquement).

Sans ce disjoncteur, une panne prolongée du service d'embeddings faisait
payer un timeout complet de 10s **à chaque appel** (message entier + repli
par clause + par segment, potentiellement plusieurs fois par tour), au lieu
d'échouer vite une fois la panne avérée.

## `request_with_retry` (générique)

2 tentatives supplémentaires (donc 3 essais au total), backoff fixe de
0.5s — volontairement simple, pas de jitter/backoff exponentiel : le budget
total doit rester largement sous les 10 secondes allouées par Rasa à une
action avant que Core ne l'abandonne. **Ne réessaie jamais sur un 4xx** :
un payload invalide ne devient pas valide en le renvoyant identique.

## Cache de capacités (300s)

`_fetch_capabilities` ([chapitre 7](07-action-diagnostic-classification.md))
garde le dernier catalogue connu même **expiré**, en cas de panne : un échec
avec un cache existant (même périmé) retombe sur ce cache plutôt que de
traiter la panne comme "aucune capacité connue" — une panne de quelques
secondes ne doit pas casser le diagnostic pour tout le monde alors qu'une
réponse récente et probablement toujours valide existe déjà. Un verrou
double-checked (`_capabilities_lock`) évite que plusieurs requêtes
concurrentes arrivant juste après l'expiration ne déclenchent chacune leur
propre appel HTTP redondant.

## Escalade vers un humain après fallbacks répétés

`_consecutive_fallback_count` remonte l'historique brut du tracker
(`tracker.events`, jamais modifié par un événement "rewind") jusqu'à la
première action qui n'est pas un fallback
(`action_default_fallback`/`action_out_of_scope`, regroupés dans
`FALLBACK_ACTION_NAMES` — les deux véhiculent la même expérience du point
de vue utilisateur : "le bot ne m'aide pas"). Au-delà de
`FALLBACK_ESCALATION_THRESHOLD = 3` fallbacks consécutifs,
`_human_support_message()` oriente vers le support humain (email/téléphone,
configurables par environnement) plutôt que de répéter un message
générique une 4ᵉ fois.

## Retrait du préambule de politesse avant classification

`_strip_greeting_preamble` (utilisée à la fois par le diagnostic,
[chapitre 7](07-action-diagnostic-classification.md), et par
`_extract_trailing_faq_question`) : un préambule ("Bonsoir, comment
allez-vous ?") dilue le vecteur moyen d'un embedding et peut faire passer
un message pourtant clair sous le seuil de similarité. Ancré en début de
chaîne uniquement — un "bonjour" mentionné ailleurs dans le message n'est
jamais touché.

## Traçabilité best-effort (`_report_agent_action`)

Envoie vers `audit.agent_actions` (voir
[16. Domaines admin](16-domaines-admin-complaints-feedback-audit.md)) —
toujours en fin de traitement d'un tour, jamais en amont d'une réponse
utilisateur, pour qu'une panne réseau ou une erreur d'écriture côté FastAPI
ne retarde ni ne casse jamais la conversation. Une exception réseau est
avalée (log niveau `INFO`, pas `WARNING`) : une trace manquante est sans
conséquence fonctionnelle, contrairement à une classification ou un
embedding manquant.
