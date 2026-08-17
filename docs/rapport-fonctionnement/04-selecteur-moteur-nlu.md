← [3. `POST /api/chat`](03-api-chat.md) | → [5. Le pipeline NLU de Rasa](05-rasa-nlu-pipeline.md)

# 4. Le sélecteur de moteur NLU

> **Rôle de ce document** : expliquer `app/domains/nlu/engines.py`, le seul
> endroit de tout le pipeline où le moteur choisi par l'utilisateur change
> réellement le comportement.

## Point d'entrée unique

`predict(model_id, text) -> NluPrediction` est la seule fonction que
`app/main.py` (et donc le frontend) connaît, quel que soit le moteur :

```python
ENGINES = {
    "rasa": ...,        # Rasa (DIETClassifier)
    "bge_logreg": ...,  # BGE-M3 + Logistic Regression
    "bge_svm": ...,     # BGE-M3 + SVM
    "bge_knn": ...,     # BGE-M3 + KNN
    "bge_mlp": ...,     # BGE-M3 + MLP
    "bge_rf": ...,      # BGE-M3 + Random Forest
}
DEFAULT_ENGINE = "rasa"
```

Le catalogue est exposé tel quel par `GET /api/models`, consommé par
`frontend/pages/chat/model.store.js` pour peupler le sélecteur — ajouter un
7ᵉ modèle n'exige qu'une entrée dans `ENGINES` plus ses artefacts entraînés,
rien côté frontend.

## Deux familles de moteurs

- **`rasa`** : `POST /model/parse` sur Rasa (`_predict_rasa`) — voir
  [5. Le pipeline NLU de Rasa](05-rasa-nlu-pipeline.md) pour le détail de ce
  pipeline.
- **`bge_*`** : encode le texte avec le modèle d'embeddings **partagé**
  (`app/shared/embeddings`, voir
  [18. Le modèle d'embeddings partagé](18-modele-embeddings-partage.md)),
  puis fait tourner un classifieur `sklearn` chargé paresseusement depuis
  `rasa/nlu_bge/model/versions/<nom>/classifier.joblib` (entraîné au
  préalable par `rasa/nlu_bge/train.py`). Toujours exécuté via
  `run_in_threadpool` : l'encodage + l'inférence sont du calcul CPU
  synchrone, jamais dans la boucle asyncio directement.

Ces classifieurs sklearn n'ont pas de fallback natif comme Rasa
(`FallbackClassifier`) : un seuil de confiance (0.70) et d'ambiguïté (0.10)
— **identiques** à ceux de Rasa — sont appliqués manuellement ; en-dessous,
l'intention devient `nlu_fallback`.

## Cache très court terme

`{(model_id, text): (posé_à, prédiction)}`, TTL 10 secondes. Chaque message
utilisateur déclenche **deux** appels à `predict()` avec le même
`(model_id, text)` : `/api/parse` (affichage) puis `/api/chat` (raccourci
FAQ), à quelques dizaines de ms d'écart. Mesuré en pratique (2026-07-30) :
l'encodage BGE-M3 domine ~90%+ du coût d'une prédiction, largement devant
l'inférence sklearn qui suit — recalculer deux fois le même embedding pour
le même texte doublerait ce coût déjà dominant, pour rien. Le TTL reste
volontairement très court : un même texte reclassifié plus tard (ex. une
relance identique) doit repasser par le modèle, ce n'est pas un cache
général de réponses NLU.

## Ce que ce choix ne pilote jamais

Voir [3. `POST /api/chat`](03-api-chat.md#3-relais-vers-rasa) : le webhook
Rasa (Core, formulaires, actions) reçoit toujours le texte brut, quel que
soit le moteur sélectionné ici. Ce choix ne pilote que l'intent/confiance
affichés par `/api/parse` et le raccourci `ask_faq` de `/api/chat`.
