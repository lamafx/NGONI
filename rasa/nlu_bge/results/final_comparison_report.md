# Comparaison Rasa vs BGE-M3 -- rapport complet

Genere par `compare.py` sur 507 exemples de test.

## Taille des modeles

| | Rasa | BGE-M3 + classifieur |
|---|---|---|
| Fichier / poids | `nlu-20260728-142329-affable-bounce.tar.gz` | `1024d (BAAI/bge-m3)` |
| Rasa (servi / latest) | nlu-20260728-142329-affable-bounce.tar.gz / nlu-20260728-142329-affable-bounce.tar.gz | - |
| Modele embarque | - | BAAI/bge-m3 (knn) |
| Entraine le | - | 2026-07-28T18:39:30 |
| Taille sur disque | 80.3 Mo | 4871.5 Mo (poids) + 7956.4 Ko (classifieur) |

## Metriques (mêmes exemples, jamais vus a l'entrainement)

| Metrique | Rasa | knn |
|---|---|---|
| Accuracy | 0.8747 | 0.9507 |
| Precision (macro) | 0.8401 | 0.9129 |
| Recall (macro) | 0.8180 | 0.8913 |
| F1 (macro) | 0.8247 | 0.8987 |
| F1 (weighted) | 0.8740 | 0.9498 |

## Latence (appel unitaire, pattern de production)

| Classifieur | Moyenne | p50 | p95 |
|---|---:|---:|---:|
| Rasa | 39.2 ms | 37.9 ms | 50.8 ms |
| knn | 306.6 ms | 275.2 ms | 402.2 ms |

## Desaccords entre les deux systemes

- Predictions differentes (Rasa != BGE-M3) : 102/507
- Les deux se trompent : 17
- Seul Rasa a raison : 8
- Seul BGE-M3 a raison : 85

## Ventilation par fichier de test

| Fichier | #Exemples | Rasa Accuracy | knn |
|---|---:|---:||---:|
| test_nlu.yml | 283 | 0.8721 | 0.9117 |
| test_nlu_500_supplement.yml | 149 | 0.9104 | 1.0000 |
| test_nlu_adversarial.yml | 75 | 0.8169 | 1.0000 |

### Seul Rasa a raison (jusqu'a 15)

| Texte | Attendu | Rasa | BGE-M3 |
|---|---|---|---|
| svp enregistrez une réclamation officielle, mon argent est parti de mon compte mais 0 pièce créditée | create_reclamation | create_reclamation | diagnostic |
| wesh l'équipe ngoni ya quelqu'un pour me repondre la ? | greet | greet | bot_challenge |
| hello hello est-ce que l'assistance automatique est en ligne ? | greet | greet | bot_challenge |
| naaaan laisse tomber tu n'as rien compris | deny | deny | rate_response_not_useful |
| fais moi un résumé du livre l'enfant noir de camara laye | out_of_scope | out_of_scope | browse_faq |
| est ce que tu peux me rédiger un CV complet pour un poste de comptable ? | out_of_scope | out_of_scope | ask_faq |
| tu réponds complètement à côté de la plaque là mon ami | rate_response_not_useful | rate_response_not_useful | bot_challenge |
| clique sur la rubrique securite et mot de passe | select_faq_category | select_faq_category | ask_faq |

### Seul BGE-M3 a raison (jusqu'a 15)

| Texte | Attendu | Rasa | BGE-M3 |
|---|---|---|---|
| est ce que l'appli marche si j'ai pas de connexion internet active ou de data ? | ask_faq | diagnostic | ask_faq |
| est-ce possible de l'utiliser sur un iphone 11 avec iOS à jour ou c'est juste reservé à android ? | ask_faq | out_of_scope | ask_faq |
| eski ya une limite maximale de stockage de pieces dans le wallet virtuel ? | ask_faq | bot_challenge | ask_faq |
| j'aimerais qu'on m'explique le système d'aide et les heures d'ouverture de l'assistance | ask_faq | nlu_fallback | ask_faq |
| esk la verification de piece d'identité est obligatoire dès la premiere connexion ? | ask_faq | diagnostic | ask_faq |
| application totalement défaillante impossible de faire un moindre retrait depuis ce matin | create_reclamation | diagnostic | create_reclamation |
| mon historique de transaction a complètement disparu de l'écran, veuiller régler le problème svp | create_reclamation | nlu_fallback | create_reclamation |
| cya l'équipe je reviens vers vous si besoin plus tard | goodbye | greet | goodbye |
| 👍 | affirm | nlu_fallback | affirm |
| c'est incorrect | deny | nlu_fallback | deny |
| pas d'accord | deny | affirm | deny |
| 👎 | deny | nlu_fallback | deny |
| non pas du tout tu fais fausse route | deny | rate_response_not_useful | deny |
| donne moi les numeros gagnants de la loterie | out_of_scope | ask_faq | out_of_scope |
| mon retrait est bloqué depuis hier | diagnostic | create_reclamation | diagnostic |

### Les deux se trompent (jusqu'a 15)

| Texte | Attendu | Rasa | BGE-M3 |
|---|---|---|---|
| l'application bug à fond, écran noir à chaque fois que je clique sur valider ma demande | create_reclamation | diagnostic | diagnostic |
| j'ai fait un dépôt depuis plus de 2 heures mais c'est toujours pas apparu c'est vraiment énervant | create_reclamation | nlu_fallback | diagnostic |
| ca fait 3 fois que la transaction echoue mais vous m'avez debité quand meme, remboursez moi | create_reclamation | out_of_scope | diagnostic |
| cc le bot j'espère que tu vas bien et que ta journée se passe bien | greet | diagnostic | goodbye |
| allez tchao je ferme l'application | goodbye | inappropriate_language | create_reclamation |
| nawak c'est pas du tout ce que j'ai demandé au depart | deny | nlu_fallback | rate_response_not_useful |
| bof non pas vraiment ce dont j'ai besoin | deny | rate_response_not_useful | rate_response_not_useful |
| absolument pas la bonne option propose autre chose | deny | out_of_scope | diagnostic |
| arrete tout c'est une erreur de ma part | deny | diagnostic | diagnostic |
| wsh zobi vous répondez jamais correctement ou quoi | inappropriate_language | nlu_fallback | rate_response_not_useful |
| c'est quoi tes compétences en tant qu'assistant virtuel ngoni ? | ask_capabilities | bot_challenge | ask_faq |
| peux tu m'expliquer en quoi tu peux me faciliter la vie sur cette appli ? | ask_capabilities | ask_faq | ask_faq |
| c'est nul tu me donnes une reponse automatique sans valeur | rate_response_not_useful | nlu_fallback | inappropriate_language |
| fais moi voir la section sur la gestion du compte et profil | select_faq_category | ask_faq | ask_faq |
| montre les infos concernant ngoni plus uniquement | select_faq_category | ask_faq | ask_faq |

Detail complet exemple par exemple : `comparison_full.csv`.
