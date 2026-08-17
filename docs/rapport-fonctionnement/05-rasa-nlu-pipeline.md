← [4. Le sélecteur de moteur NLU](04-selecteur-moteur-nlu.md) | → [6. Rasa Core, policies, domaine](06-rasa-core-policies-domain.md)

# 5. Le pipeline NLU de Rasa

> **Rôle de ce document** : décrire précisément les composants du pipeline
> NLU de Rasa (`rasa/config.yml`), pas la logique de dialogue (voir
> [chapitre 6](06-rasa-core-policies-domain.md) pour ça).

## Le pipeline actuel

```yaml
language: fr
pipeline:
  - name: SpacyNLP
    model: "fr_core_news_md"
  - name: SpacyTokenizer
  - name: SpacyFeaturizer
    pooling: "mean"
  - name: CountVectorsFeaturizer
    analyzer: "word"
    min_ngram: 1
    max_ngram: 2
    min_df: 1
  - name: CountVectorsFeaturizer
    analyzer: "char"
    min_ngram: 3
    max_ngram: 5
    min_df: 1
  - name: DIETClassifier
    epochs: 80
    constrain_similarities: true
  - name: FallbackClassifier
    threshold: 0.70
    ambiguity_threshold: 0.10
```

Dans l'ordre : `SpacyNLP` charge le modèle linguistique français
(`fr_core_news_md`) ; `SpacyTokenizer` découpe en tokens ; `SpacyFeaturizer`
produit des vecteurs denses (pooling par moyenne) ; les deux
`CountVectorsFeaturizer` ajoutent des features lexico-syntaxiques — l'un sur
mots entiers (1 à 2-grammes), l'autre sur sous-chaînes de caractères (3 à
5-grammes, utile pour la robustesse aux fautes de frappe/variantes
morphologiques) ; `DIETClassifier` (80 epochs, similarités contraintes)
prédit l'intention et les entités ; `FallbackClassifier` bascule vers
`nlu_fallback` si la confiance finale est sous 0.70, ou si les deux
meilleures intentions sont à moins de 0.10 d'écart.

## ⚠️ Écart trouvé avec la documentation existante

[08-pipeline-traitement.md](../08-pipeline-traitement.md) (§8.4) mentionne
encore un composant `VocabularyCoverageGuard` forçant la confiance à 0 si
aucun mot du message n'est reconnu du vocabulaire d'entraînement. **Ce
composant n'apparaît plus dans `rasa/config.yml` actuel** — cohérent avec
`rasa/components/vocabulary_guard.py` figurant comme suppression en cours
dans les changements non commités de la branche `opt-embedding` (constaté
via `git status` le 2026-07-31 : `deleted: rasa/components/vocabulary_guard.py`).

Le pipeline réellement actif aujourd'hui est celui listé ci-dessus, **sans**
garde-fou de vocabulaire personnalisé. Ce chapitre de la documentation
existante devra être corrigé si cette suppression est confirmée définitive
— voir [19. Vérifications et écarts](19-verifications-ecarts-doc.md).

## `assistant_id`

`rasa/config.yml` porte `assistant_id: 20260728-142324-chilly-frank` —
identifiant généré par Rasa, sans signification fonctionnelle, change à
chaque `rasa init`/régénération de config.

## Ce que ce pipeline ne décide jamais

La classification NLU (ce chapitre) ne décide d'aucune action — c'est le
rôle des policies de Rasa Core, voir
[6. Rasa Core, policies, domaine](06-rasa-core-policies-domain.md).
