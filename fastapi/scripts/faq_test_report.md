# Rapport de qualite FAQ -- corpus de 200 requetes

Positifs : 156 (paraphrases des 26 questions du catalogue) -- Negatifs : 44 (salutations, hors-sujet, diagnostic/reclamation)

Genere le 2026-07-30 03:47:07 -- modele d'embedding : voir app/shared/embeddings/service.py (MODEL_NAME)

## Seuils actuellement configures

- **DEFAULT_THRESHOLD = 0.55** : TP=126 FP=20 FN=30 TN=24 -- precision=0.863 rappel=0.808 F1=0.834 accuracy=0.750
- **SECONDARY_THRESHOLD = 0.4** : TP=131 FP=43 FN=25 TN=1 -- precision=0.753 rappel=0.840 F1=0.794 accuracy=0.660

## Balayage de seuils (0.30 a 0.80, pas de 0.05)

| Seuil | TP | FP | FN | TN | Precision | Rappel | F1 | Accuracy |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.30 | 131 | 44 | 25 | 0 | 0.749 | 0.840 | 0.792 | 0.655 |
| 0.35 | 131 | 44 | 25 | 0 | 0.749 | 0.840 | 0.792 | 0.655 |
| 0.40 | 131 | 43 | 25 | 1 | 0.753 | 0.840 | 0.794 | 0.660 |
| 0.45 | 131 | 38 | 25 | 6 | 0.775 | 0.840 | 0.806 | 0.685 |
| 0.50 | 128 | 31 | 28 | 13 | 0.805 | 0.821 | 0.813 | 0.705 |
| 0.55 | 126 | 20 | 30 | 24 | 0.863 | 0.808 | 0.834 | 0.750 |
| 0.60 | 117 | 11 | 39 | 33 | 0.914 | 0.750 | 0.824 | 0.750 |
| 0.65 | 111 | 7 | 45 | 37 | 0.941 | 0.712 | 0.810 | 0.740 |
| 0.70 | 101 | 1 | 55 | 43 | 0.990 | 0.647 | 0.783 | 0.720 |
| 0.75 | 87 | 1 | 69 | 43 | 0.989 | 0.558 | 0.713 | 0.650 |
| 0.80 | 66 | 0 | 90 | 44 | 1.000 | 0.423 | 0.595 | 0.550 |

**Meilleur F1 sur ce balayage : seuil=0.55 (F1=0.834)** -- point de depart pour un nouveau DEFAULT_THRESHOLD, a confirmer par relecture manuelle des cas ci-dessous avant d'etre adopte.

## Cas mal classes au seuil DEFAULT_THRESHOLD actuel

### Faux positifs (20) -- ne devraient renvoyer aucune reponse FAQ

| Requete | Score | Reponse renvoyee a tort |
|---|---:|---|
| 'hello' | 0.5602 | "Comment contacter l'assistance ?" |
| 'je vous remercie pour votre aide' | 0.6582 | "Comment contacter l'assistance ?" |
| "peux-tu m'aider en mathématiques" | 0.5983 | "Comment contacter l'assistance ?" |
| 'mon compte est bloqué depuis hier' | 0.6964 | 'Comment obtenir la vérification de mon compte ?' |
| "je n'arrive plus à retirer mon argent, ça coince depuis ce matin" | 0.5778 | 'Comment obtenir la vérification de mon compte ?' |
| "j'ai acheté des pièces mais elles n'apparaissent pas sur mon compte" | 0.6624 | 'Comment obtenir la vérification de mon compte ?' |
| 'mon retrait est en attente depuis trois jours' | 0.7840 | 'Combien de temps prend un retrait ?' |
| 'mon KYC est bloqué depuis une semaine, personne ne répond' | 0.5978 | 'Quels documents sont nécessaires pour le KYC ?' |
| "l'application plante à chaque fois que je l'ouvre" | 0.5929 | "Comment changer la langue de l'application ?" |
| 'je ne reçois plus aucune notification depuis hier' | 0.5754 | 'Comment obtenir la vérification de mon compte ?' |
| "mon paiement a été débité mais je n'ai rien reçu" | 0.6308 | 'Comment obtenir la vérification de mon compte ?' |
| 'des pièces ont disparu de mon compte' | 0.6952 | 'Comment obtenir la vérification de mon compte ?' |
| 'mon compte a été suspendu sans explication' | 0.6943 | 'Comment obtenir la vérification de mon compte ?' |
| 'je veux déposer une réclamation officielle' | 0.6294 | 'Comment obtenir la vérification de mon compte ?' |
| 'ouvrez-moi un ticket pour ce problème' | 0.6135 | 'Comment obtenir la vérification de mon compte ?' |
| 'je veux parler à un conseiller humain' | 0.6911 | "Comment contacter l'assistance ?" |
| 'je souhaite porter plainte concernant ce service' | 0.5909 | 'Comment obtenir la vérification de mon compte ?' |
| 'créez un dossier de réclamation pour moi' | 0.6095 | 'Comment obtenir la vérification de mon compte ?' |
| 'cette application est vraiment nulle en ce moment' | 0.5822 | 'Pourquoi certaines fonctionnalités ne sont-elles pas encore disponibles ?' |
| 'je suis très déçu par le service client' | 0.5797 | "Comment contacter l'assistance ?" |

### Faux negatifs (30) -- auraient du matcher la bonne question

| Requete | Attendu | Obtenu | Score |
|---|---|---|---:|
| "je veux m'inscrire sur l'application, comment on fait ?" | creer-compte-ngoni | contacter-support | 0.7065 |
| 'procédure pour ouvrir un compte' | creer-compte-ngoni | verification-compte | 0.6992 |
| "j'aimerais m'inscrire, quelle est la démarche ?" | creer-compte-ngoni | contacter-support | 0.6852 |
| 'mon compte fonctionne sur tablette et mobile ?' | puis-je-utiliser-ngoni-sur-plusieurs-appareils-ea01f558 | verification-compte | 0.6748 |
| 'jai zapé mon mdp koman on fé' | reinitialiser-mot-de-passe | comment-retirer-revenus | 0.4890 |
| 'quelles sont les façons de monétiser mon contenu' | comment-un-cr-ateur-peut-il-gagner-de-l-argent-sur-la-plateforme-97c1ea25 | video-privee-payante | 0.6258 |
| 'comment monétiser mon audience sur ngoni' | comment-un-cr-ateur-peut-il-gagner-de-l-argent-sur-la-plateforme-97c1ea25 | creer-compte-ngoni | 0.6189 |
| 'koman on ash7t des piece sur ngoni' | acheter-pieces-ngoni | acheter-pieces-ngoni | 0.4967 |
| "comment recharger en pièces sur l'appli" | acheter-pieces-ngoni | changer-langue-application | 0.5283 |
| 'koman marsh le systeme de piece' | fonctionnement-pieces-ngoni | programme-recompenses | 0.4443 |
| 'je comprends pas comment fonctionnent les coins' | fonctionnement-pieces-ngoni | fonctionnalites-non-disponibles | 0.5565 |
| 'koman on pe paye sur ngoni, kel moyen' | moyens-paiement-disponibles | comment-retirer-revenus | 0.5029 |
| 'orange money ça marche pour payer sur ngoni ?' | moyens-paiement-disponibles | acheter-pieces-ngoni | 0.6535 |
| "comment je récupère l'argent que j'ai gagné" | comment-retirer-revenus | verification-compte | 0.6619 |
| 'comment encaisser mes gains sur ngoni' | comment-retirer-revenus | acheter-pieces-ngoni | 0.5989 |
| 'sa pran combien de tem 1 retré normalman' | delai-retrait | delai-retrait | 0.4953 |
| "quels papiers il me faut pour la vérification d'identité" | quels-documents-sont-n-cessaires-pour-le-kyc-cbf8a9ce | verification-compte | 0.7462 |
| 'liste des pièces à fournir pour vérifier mon identité' | quels-documents-sont-n-cessaires-pour-le-kyc-cbf8a9ce | verification-compte | 0.7049 |
| "quels justificatifs sont demandés pour la vérification d'identité" | quels-documents-sont-n-cessaires-pour-le-kyc-cbf8a9ce | verification-compte | 0.7183 |
| 'comment protéger le compte de mon enfant' | controle-parental | verification-compte | 0.6814 |
| 'koman on fé 1 don pandan 1 live' | comment-fonctionne-le-syst-me-de-dons-pendant-un-live-76fd5fc0 | comment-fonctionne-le-syst-me-de-dons-pendant-un-live-76fd5fc0 | 0.4605 |
| 'comment offrir un cadeau à un créateur en direct' | comment-fonctionne-le-syst-me-de-dons-pendant-un-live-76fd5fc0 | soutenir-createur | 0.7193 |
| 'koman on not le réponse de lasistan' | notation-reponses-assistant | contacter-support | 0.4118 |
| 'où puis-je consulter la FAQ' | o-trouver-la-foire-aux-questions-a039612a | contacter-support | 0.6927 |
| 'ou ge trouv la faq stp' | o-trouver-la-foire-aux-questions-a039612a | contacter-support | 0.5445 |
| 'koman on propoz 1 amelioration' | proposer-amelioration | proposer-amelioration | 0.5239 |
| 'pk certain fonctionalite son pa dispo' | fonctionnalites-non-disponibles | fonctionnalites-non-disponibles | 0.5415 |
| 'tu peux me présenter NGONI' | quest-ce-que-ngoni | acheter-pieces-ngoni | 0.7099 |
| 'à quoi sert cette application' | quest-ce-que-ngoni | changer-langue-application | 0.5946 |
| "c'est koi ngoni en fet" | quest-ce-que-ngoni | creer-compte-ngoni | 0.4702 |
