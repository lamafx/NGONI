← [17. Retour jusqu'à l'utilisateur](17-retour-reponse-utilisateur.md) | → [19. Vérifications effectuées et écarts trouvés](19-verifications-ecarts-doc.md)

# 18. Le modèle d'embeddings partagé

> **Rôle de ce document** : `app/shared/embeddings` — pourquoi un seul
> modèle sert toute la plateforme, chargé une seule fois, et qui l'utilise
> réellement.

## Un seul exemplaire, côté FastAPI uniquement

Le modèle (BGE-M3, après passage successif par `intfloat/multilingual-e5-small`
puis `e5-base`) tourne **uniquement** dans le process FastAPI — ni Rasa ni
le serveur Actions ne chargent leur propre copie. Actions y accède par HTTP
(`POST /embeddings/query` et `/embeddings/query/batch`), jamais en process.

## Préchargé au démarrage, pas au premier appel

`app/main.py::startup` appelle `get_embedding_model()` **avant** d'accepter
du trafic (avec le préchauffage du Capability Registry, voir
[13. Le registre](13-diagnostic-engine-registry.md)) :

> Sans ça, la première requête utilisateur après chaque redémarrage payait
> le coût de chargement (~10-20s, avec vérifications réseau vers
> huggingface.co) dans le budget des 10 secondes allouées par Rasa à
> `_fetch_capabilities`/`_embed_message`, provoquant un faux "service
> indisponible" — constaté en pratique à deux reprises.

## Qui l'utilise

1. **Recherche FAQ sémantique** (`FaqService.find_best_answer`, voir
   [chapitres 3](03-api-chat.md) et [10](10-action-faq.md)).
2. **Classification diagnostic** (embeddings précalculés des problèmes du
   catalogue au [chapitre 13](13-diagnostic-engine-registry.md), embedding
   du message utilisateur au [chapitre 7](07-action-diagnostic-classification.md)).
3. **Les 5 classifieurs `bge_*`** du sélecteur de modèle NLU (voir
   [4. Le sélecteur de moteur NLU](04-selecteur-moteur-nlu.md)) — encodent
   le texte avec ce même modèle avant de faire tourner leur classifieur
   sklearn entraîné séparément.

## Historique des seuils de similarité

Chaque changement de modèle (e5-small → e5-base → BGE-M3) a nécessité un
**recalibrage** des seuils de similarité cosinus utilisés en classification
diagnostic (voir [chapitre 7](07-action-diagnostic-classification.md)) —
ces seuils ne sont pas des constantes universelles, ils sont valables pour
un modèle d'embeddings donné :

- e5-small → e5-base : seuil `MIN_EMBEDDING_SIMILARITY` recalibré de 0.83 à
  0.84 après mesure d'un taux de faux positifs de 65% sur un corpus de 20
  messages neutres.
- e5-base → BGE-M3 (2026-07-30) : les phrases complètes restent largement
  au-dessus de l'ancien seuil, mais les messages **courts** (1-3 mots)
  dégradent nettement — un second plancher dédié
  (`KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY = 0.40`) a été introduit
  spécifiquement pour le repêchage par mot-clé unique.
- Recalibrage final (2026-07-30, sur un corpus de 72 requêtes) : le seuil
  principal est descendu à **0.75**, dominant strictement l'ancien 0.84
  (même 0 faux positif, meilleur rappel, F1 = 0.990).

Ce recalibrage récurrent est documenté comme une **limite assumée** : le
corpus de test (72 requêtes, 8 problèmes au catalogue) reste petit face à
la diversité réelle des formulations utilisateur — à revalider si le
catalogue grossit significativement ou si l'usage réel montre trop de faux
positifs/négatifs.
