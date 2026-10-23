# Démonstration devant le jury — parcours « vérification d'identité »

Objectif : montrer qu'un **conseiller humain traite réellement les données d'un usager** — il consulte son compte, confronte la pièce d'identité au compte, décide, et sa décision change l'état du compte, constaté ensuite par l'assistant lui-même. Rien n'est scripté : chaque réponse vient du moteur et de la base.

## Avant le passage

1. Allumer : `scripts\demarrer-live.cmd` (attendre « Pret », 5 à 8 min).
2. Remettre le compte de démo à zéro :
   ```
   docker compose exec fastapi python scripts/compte_demo.py reinitialiser
   ```
3. Ouvrir deux onglets :
   - **Client** : http://localhost:5173/?compte=a40e0e00-2006-4514-8000-000000000001#/chat
   - **Conseiller** : http://localhost:5173/#/agent/live
4. Avoir sous la main `demo\carteIDFront.png` (la CNI) et `demo\profil.jpeg` (pour montrer un refus).

État de départ du compte : AYEKOE Adou Eric Baruch Deverin, né le 14/05/2006, Côte d'Ivoire, vérification d'identité **refusée** il y a 3 jours (photo floue).

## Le parcours (≈ 6 min)

Chaque message du client prend **10 à 35 s** (modèle de langue sur processeur, sans GPU), jusqu'à 50 s pour un long message.

| # | Où | Action | Ce qui se passe (réel) |
|---|---|---|---|
| 1 | Client | « ma vérification d'identité est bloquée » puis « oui » | Le diagnostic interroge le user service : **refusée, motif « photo floue »**. |
| 2 | Client | Trombone → `profil.jpeg` → envoyer | Filtre OCR : **« Fichier non adapté »**, ce n'est ni une CNI ni un passeport. |
| 3 | Client | Trombone → `carteIDFront.png` → envoyer | OCR : CNI reconnue, 10 champs extraits, pièce **transmise pour vérification** (soumission KYC « en attente » créée). |
| 4 | Client | « peux-tu vérifier ma vérification d'identité ? » puis « oui » | Le diagnostic répond désormais **« en cours d'examen »**. |
| 5 | Client | Bouton **Contactez-nous** | La conversation entre dans la file des conseillers. |
| 6 | Conseiller | Cloche → « Pièce d'identité à vérifier », ou la conversation en attente → **Prendre en charge** | Le bot se tait : c'est le conseiller qui répond. |
| 7 | Conseiller | **Dossier client** | Compte (user service), historique KYC, portefeuille (wallet service), la pièce et ses champs, **confrontation pièce ↔ compte** (nom, naissance, nationalité, validité). Bandeau : consultation tracée. |
| 8 | Conseiller | **Valider l'identité** | Le compte passe **VERIFIED** dans la base, la décision est tracée au journal, une réponse au client est proposée. |
| 9 | Conseiller | Envoyer la réponse proposée, puis **Clore** | Le client la reçoit et l'assistant reprend la main. |
| 10 | Client | Cloche : « Votre identité a été vérifiée par un conseiller » ; puis « peux-tu vérifier ma vérification d'identité ? » + « oui » | L'assistant répond **« déjà validée »** : il constate la décision du conseiller. |

Variante « refus » à l'étape 8 : **Refuser la pièce** + motif (ex. « Nom différent de celui du compte ») → compte REJECTED, le client est notifié avec le motif.

Pour montrer la traçabilité : rouvrir le dossier, bloc **Note interne et journal** — qui a consulté, validé, refusé, quand.

## Formulations fiables

- Déclenchent le diagnostic KYC : « ma vérification d'identité est bloquée », « peux-tu vérifier ma vérification d'identité ? », « j'ai un problème avec ma vérification d'identité ».
- **À éviter** : « où en est ma vérification ? », « mon KYC est validé ? » → compris comme « statut de réclamation ».
- Un long message est bien compris (intention + entités : montant, date, opérateur), mais prend 40 à 50 s : prévenir le jury avant d'envoyer.

## Si quelque chose bloque

- Réponse très lente au premier message : le modèle se recharge, attendre (jusqu'à 90 s).
- « Service momentanément indisponible » : `docker compose ps`, puis `docker compose restart fastapi`.
- Plan de secours : la démonstration rejouée http://localhost:5173/?demo=1#/chat (scénario filmé, réponses écrites d'avance — à présenter comme telle).

## Ce qui est réel, ce qui ne l'est pas

- **Réel** : compréhension des messages, diagnostic, OCR et filtre des pièces, file des conseillers, dossier client, décision KYC, journal d'audit, notifications.
- **Services wallet / user** : ce sont les services de ce dépôt (`fastapi/wallet_service`, `fastapi/user_service`), qui reproduisent les contrats de ngoni-wallet-service et ngoni-user-service sur une copie de leur base. En production, le moteur appellerait les vrais services, avec les mêmes routes.
- **Rejoué** : uniquement `?demo=1` et l'écran `/agent` (scène filmée).
- **Limite assumée** : pas d'authentification réelle (secret partagé côté administration, compte choisi dans l'adresse côté client).
