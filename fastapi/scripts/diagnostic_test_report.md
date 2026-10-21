# Rapport de qualite du matching diagnostic -- corpus de 72 requetes

Positifs : 52 (paraphrases des 8 problemes wallet+user, cible sur les collisions deja documentees dans les manifestes) -- Negatifs : 20 (salutations, questions FAQ generales, hors-sujet)

Genere le 2026-08-20 20:34:18

**Limite assumee** : mesure le score d'embedding brut via POST /diagnostic/debug/classify, PAS le pipeline complet de desambiguisation (tiebreak mots-cles, repechage, repli par clause) qui vit cote rasa/actions/diagnostic.py et peut corriger certains cas signales ici. Voir le docstring de ce script.

## Seuil actuellement configure (MIN_EMBEDDING_SIMILARITY = 0.75)

TP=51 FP=0 FN=1 TN=20 -- precision=1.000 rappel=0.981 F1=0.990 accuracy=0.986

## Balayage de seuils (0.40 a 0.90, pas de 0.05)

| Seuil | TP | FP | FN | TN | Precision | Rappel | F1 | Accuracy |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.40 | 52 | 20 | 0 | 0 | 0.722 | 1.000 | 0.839 | 0.722 |
| 0.45 | 52 | 20 | 0 | 0 | 0.722 | 1.000 | 0.839 | 0.722 |
| 0.50 | 52 | 17 | 0 | 3 | 0.754 | 1.000 | 0.860 | 0.764 |
| 0.55 | 52 | 12 | 0 | 8 | 0.812 | 1.000 | 0.897 | 0.833 |
| 0.60 | 52 | 7 | 0 | 13 | 0.881 | 1.000 | 0.937 | 0.903 |
| 0.65 | 52 | 2 | 0 | 18 | 0.963 | 1.000 | 0.981 | 0.972 |
| 0.70 | 51 | 0 | 1 | 20 | 1.000 | 0.981 | 0.990 | 0.986 |
| 0.75 | 51 | 0 | 1 | 20 | 1.000 | 0.981 | 0.990 | 0.986 |
| 0.80 | 51 | 0 | 1 | 20 | 1.000 | 0.981 | 0.990 | 0.986 |
| 0.85 | 43 | 0 | 9 | 20 | 1.000 | 0.827 | 0.905 | 0.875 |
| 0.90 | 34 | 0 | 18 | 20 | 1.000 | 0.654 | 0.791 | 0.750 |

**Meilleur F1 sur ce balayage : seuil=0.70 (F1=0.990)**

## Confusions (collisions inter-problemes) au seuil actuel

Aucune confusion nette (candidat errone au-dessus du seuil) sur ce corpus.

## Faux positifs (negatifs matches a tort) au seuil actuel

Aucun.

## Faux negatifs (score sous le seuil alors que le probleme est le bon candidat) au seuil actuel

| Requete | Probleme attendu (bon candidat, score trop bas) | Score |
|---|---|---:|
| "le consentement parental n'a jamais été traité" | parental_consent_status | 0.6765 |
