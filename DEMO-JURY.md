# Démonstration devant le jury — parcours « vérification d'identité »

Objectif : montrer qu'un **conseiller humain traite réellement les données d'un usager** — il consulte son compte, confronte la pièce d'identité au compte, décide, et sa décision change l'état du compte, constaté ensuite par l'assistant lui-même. Rien n'est scripté : chaque réponse vient du moteur et de la base.

Parcours vérifié de bout en bout le 23/10/2026 (navigateur réel, pile Docker).

## Avant le passage

1. Allumer : `scripts\demarrer-live.cmd` (attendre « Pret », 5 à 8 min).
2. Remettre le compte de démo à zéro :
   ```
   docker compose exec fastapi python scripts/compte_demo.py reinitialiser
   ```
3. Ouvrir **deux fenêtres de navigateur distinctes** (ou une fenêtre normale + une privée : chaque session a sa propre connexion) sur http://localhost:5173 :
   - fenêtre 1 : bouton **Adou Ayekoe** (client) ;
   - fenêtre 2 : bouton **Awa Koné** (conseillère).
4. Avoir sous la main `demo\carteIDFront.png` (la CNI) et `demo\profil.jpeg` (pour montrer un refus).

État de départ du compte : AYEKOE Adou Eric Baruch Deverin, né le 14/05/2006, Côte d'Ivoire, vérification d'identité **refusée** il y a 3 jours (photo floue), solde 45 000 FCFA.

## Le parcours (≈ 6 min)

Chaque message du client prend **15 à 45 s** (modèle de langue sur processeur, sans GPU), parfois 60 s. L'écran affiche « Analyse de votre message en cours… (N s) » pendant l'attente.

| # | Où | Action | Ce qui se passe (réel) |
|---|---|---|---|
| 1 | Client | « ma vérification d'identité est bloquée » puis « oui » | Le diagnostic interroge le user service : **refusée, motif « photo floue »**. |
| 2 | Client | Trombone → `profil.jpeg` → envoyer | Filtre OCR : **« Fichier non adapté »** — ni une CNI ni un passeport. |
| 3 | Client | Trombone → `carteIDFront.png` → envoyer | OCR : CNI reconnue, 10 champs extraits, pièce **transmise pour vérification** (soumission KYC « en attente »). |
| 4 | Client | « où en est ma vérification ? » puis « oui » | Le diagnostic répond **« en cours d'examen »**. |
| 5 | Client | Bouton **Contactez-nous** | La conversation entre dans la file des conseillers. |
| 6 | Conseillère | Cloche → « Pièce d'identité à vérifier » (ou la conversation en attente) → **Prendre en charge** | Le bot se tait : c'est la conseillère qui répond. |
| 7 | Conseillère | **Dossier client** | Compte (user service), historique KYC, portefeuille (wallet service), la pièce et ses champs, **confrontation pièce ↔ compte** (4 concordances). Bandeau : consultation tracée. |
| 8 | Conseillère | **Valider l'identité** | Compte **VERIFIED** dans la base, décision tracée, image de la pièce effacée (conservation), réponse au client proposée. |
| 9 | Conseillère | **Envoyer au client et clore le dossier** | Le client reçoit la réponse, l'échange est clos, l'assistant reprend la main. |
| 10 | Client | Cloche : « Votre identité a été vérifiée par un conseiller » ; puis « peux-tu vérifier ma vérification d'identité ? » + « oui » | L'assistant répond **« Votre vérification d'identité est déjà validée »** : il constate la décision de la conseillère. |

Variantes :
- **Refus** à l'étape 8 : *Refuser la pièce* + motif (ex. « Nom différent de celui du compte ») → compte REJECTED, client notifié avec le motif.
- **Transfert** : depuis le poste conseiller, « Transférer à… » Yao Kouassi (se connecter avec `yao.kouassi` pour le montrer).
- **Pièce jointe** : bouton *Pièce jointe* du poste conseiller → le client reçoit l'image ou le PDF.
- **Sécurité** : connecté en conseiller, ouvrir `/#/admin` → refusé (« réservé à l'administration »).
- **Capacités** (connexion `fatou.diarra`) : Administration → Capacités — 19 intentions, 20 problèmes résolus automatiquement, bouton « Tester » par problème.

Pour la traçabilité : dans le dossier, bloc **Note interne et journal** — qui a consulté, validé, refusé, quand.

## Formulations fiables

- Diagnostic d'identité : « ma vérification d'identité est bloquée », « où en est ma vérification ? », « peux-tu vérifier ma vérification d'identité ? », « mon KYC est validé ? ».
- Une question de réclamation reste une réclamation : « où en est ma réclamation ? ».
- Les 19 autres problèmes, une phrase chacun : voir Administration → Capacités (colonne « Exemple de demande »).
- Un long message est bien compris (intention + entités : montant, date, opérateur), mais prend 40 à 60 s : prévenir le jury avant d'envoyer.

## Si quelque chose bloque

- Très lent au tout premier message : le modèle se recharge (jusqu'à 90 s). Le préchauffage l'évite s'il est allé au bout.
- « Service momentanément indisponible » : `docker compose ps`, puis `docker compose restart fastapi`.
- Session expirée (12 h) : se reconnecter.
- Plan de secours : http://localhost:5173/?demo=1#/chat — démonstration rejouée (réponses écrites d'avance, à présenter comme telle).

## Ce qui est réel, ce qui ne l'est pas

- **Réel** : compréhension des messages (19 intentions), diagnostic (20 problèmes), OCR et filtre des pièces, file des conseillers, dossier client, décision KYC, journal d'audit, notifications, authentification par rôle.
- **Services wallet / user** : ce sont les services de ce dépôt (`fastapi/wallet_service`, `fastapi/user_service`), qui reproduisent les contrats de ngoni-wallet-service et ngoni-user-service sur une copie de leur base. En production, le moteur appellerait les vrais services, avec les mêmes routes.
- **Rejoué** : uniquement `?demo=1` et l'écran `/agent` (scène filmée).
- **Sécurité** : mots de passe hachés (PBKDF2-SHA256), jetons signés (HMAC-SHA256, 12 h), rôles vérifiés par le serveur, aucun secret dans le code de la page. Limite assumée : comptes de démonstration à mot de passe commun, pas de renouvellement de jeton ni de double authentification.
