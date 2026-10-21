Crée entièrement le frontend de **NGONI IA**, le système intelligent de support client intégré à la plateforme sociale NGONI.

## CONTEXTE

Je vais fournir plusieurs images de référence :

1. **Image de l'interface Chat** → référence fonctionnelle et UX du chat utilisateur.
2. **Image de l'interface Agent** → référence fonctionnelle et UX du poste de travail de l'agent humain.
3. **Image de l'interface Admin** → référence fonctionnelle et UX de l'espace d'administration.
4. **Image de l'icône Support NGONI** → référence officielle pour l'identité visuelle et l'icône de NGONI IA.

Les trois premières images sont des **baselines visuelles** : elles permettent de comprendre précisément la structure, les composants et l'organisation souhaités.

La quatrième image est la **source de vérité pour l'identité visuelle de NGONI IA**, notamment la palette de couleurs et l'icône Support.

Il n'existe actuellement **aucun code frontend existant**.

Tu dois donc créer le frontend **entièrement à partir de zéro**.

---

# 1. STRUCTURE DU PROJET

Crée à la racine du projet un dossier nommé exactement :

```text
frontfolder
```

Toute l'application frontend doit être organisée à l'intérieur de ce dossier.

Créer une structure propre et professionnelle, adaptée à une application web moderne.

Par exemple :

```text
frontfolder/
│
├── src/
│   ├── components/
│   ├── pages/
│   ├── layouts/
│   ├── assets/
│   ├── styles/
│   ├── services/
│   └── ...
│
├── public/
│   └── assets/
│
├── package.json
├── README.md
└── ...
```

Tu peux adapter cette structure selon le framework utilisé, mais elle doit rester claire, modulaire et maintenable.

---

# 2. IMAGES DE RÉFÉRENCE

Les images fournies doivent être considérées comme des **références de conception**.

Ne les affiche pas simplement comme des images dans le frontend.

Tu dois **reproduire leur logique et leur design sous forme de véritables composants UI**.

Les images doivent uniquement servir à comprendre :

* la disposition ;
* les proportions ;
* la hiérarchie ;
* les composants ;
* les interactions ;
* le style ;
* l'organisation générale.

---

# 3. ICÔNE SUPPORT

L'image contenant l'icône Support doit être utilisée comme **icône officielle de NGONI IA**.

Place cette ressource dans les assets du projet, par exemple :

```text
frontfolder/
└── src/
    └── assets/
        └── ngoni-support-icon.png
```

Utilise cette icône dans :

* l'avatar de NGONI IA ;
* les messages de l'IA ;
* les résumés générés par l'IA ;
* les notifications ;
* les éléments indiquant une action de l'IA ;
* l'espace administration ;
* les éléments représentant le passage IA → humain.

**Ne crée pas une nouvelle icône.**

Ne remplace pas l'icône par un robot ou une illustration générique.

---

# 4. PALETTE DE COULEURS

Analyse l'image de l'icône Support et utilise ses couleurs pour construire le design system.

La palette doit être extraite visuellement de cette image.

Définir :

* couleur primaire ;
* couleur secondaire ;
* couleur d'accent ;
* couleurs de fond ;
* couleurs de texte ;
* couleurs de bordure ;
* couleurs d'état.

Les couleurs doivent être utilisées de manière élégante et équilibrée.

Privilégier :

**70–80 % de tons neutres et fonds clairs**

**15–20 % de couleurs NGONI**

**environ 5 % de couleurs d'accent**

Ne surcharge pas les interfaces.

L'objectif est d'obtenir une interface :

**claire + professionnelle + moderne + lisible.**

---

# 5. DESIGN SYSTEM COMMUN

Les trois applications doivent partager exactement le même langage visuel.

Créer des composants réutilisables pour :

* boutons ;
* badges ;
* cartes ;
* champs ;
* avatars ;
* messages ;
* notifications ;
* menus ;
* tableaux ;
* modales ;
* indicateurs de statut ;
* timelines ;
* barres de navigation.

Utiliser :

* une typographie moderne ;
* des espacements cohérents ;
* des bordures fines ;
* des coins légèrement arrondis ;
* des ombres très légères ;
* des icônes cohérentes.

Le design doit être suffisamment sobre pour donner l'impression d'un véritable produit commercial.

---

# 6. INTERFACE CHAT UTILISATEUR

Créer une page :

```text
/chat
```

Elle doit permettre à un utilisateur de dialoguer avec NGONI IA.

### Sidebar

Afficher :

**NGONI IA**

avec l'icône Support.

Navigation :

* Nouvelle conversation
* Conversations
* FAQ
* Mes demandes
* Assistance

### Conversation

Créer une conversation réaliste avec :

Utilisateur :

> Bonjour, je voudrais savoir comment tu fonctionnes.

NGONI IA :

> Bonjour ! Je peux répondre à vos questions, vous accompagner dans l'utilisation de NGONI et effectuer certaines opérations lorsque cela est autorisé.

Puis :

Utilisateur :

> J'ai une vidéo dans mes brouillons. Peux-tu la publier ?

NGONI IA :

> J'ai trouvé une vidéo dans vos brouillons. Souhaitez-vous que je lance sa publication ?

Afficher :

**Publier la vidéo**

Après confirmation :

**Publication en cours...**

Puis :

**Votre vidéo a été publiée avec succès.**

Prévoir les états :

* chargement ;
* succès ;
* erreur ;
* confirmation ;
* vérification requise ;
* escalade.

---

# 7. INTERFACE AGENT HUMAIN

Créer une page :

```text
/agent
```

Elle doit être un véritable poste de travail de support.

### Sidebar

* Conversations
* En attente
* Escalades
* Mes dossiers
* Historique
* Clients

### Liste des conversations

Afficher plusieurs conversations réalistes.

Exemple :

**#4582 — Vérification d'identité**

Utilisateur #82741

**Escaladée il y a 2 min**

### Conversation

Afficher l'historique complet.

Afficher clairement :

**NGONI IA → Agent humain**

### Résumé IA

Afficher :

**Résumé généré par NGONI IA**

> L'utilisateur souhaitait publier une vidéo présente dans ses brouillons. La vidéo a été publiée avec succès. Une vérification d'identité était ensuite requise. Trois tentatives ont échoué. La procédure automatique a été interrompue et la demande a été transmise à un conseiller.

### Timeline

```text
Demande reçue
↓
Vidéo identifiée
↓
Publication exécutée
↓
Vérification demandée
↓
Tentative 1 échouée
↓
Tentative 2 échouée
↓
Tentative 3 échouée
↓
Escalade humaine
```

### Informations client

Afficher :

* profil ;
* statut ;
* historique ;
* activité récente ;
* demandes précédentes.

### Réponse agent

Créer une zone :

**Écrivez votre réponse au client...**

Boutons :

* envoyer ;
* pièce jointe ;
* note interne ;
* prendre en charge ;
* résoudre ;
* transférer.

---

# 8. INTERFACE ADMINISTRATION

Créer une page :

```text
/admin
```

Créer un dashboard professionnel.

### Navigation

* Vue d'ensemble
* Conversations
* Demandes
* Diagnostics
* Escalades
* Agents
* Statistiques
* Base de connaissances
* Paramètres

### KPI

Afficher :

**Conversations aujourd'hui**
1 284

**Résolution automatique**
91,8 %

**Demandes escaladées**
106

**Diagnostics exécutés**
438

**Temps moyen de réponse**
2,4 s

**Agents actifs**
12

### Graphiques

Afficher :

* volume des conversations ;
* demandes résolues ;
* demandes escaladées ;
* activité du système.

### État des services

Afficher :

* NGONI IA — Opérationnel
* NLU — Opérationnel
* Recherche sémantique — Opérationnelle
* Diagnostic Engine — Opérationnel
* Video Service — Opérationnel
* User Service — Opérationnel
* Wallet Service — Opérationnel

### Escalades

Afficher une section :

**Escalades nécessitant une intervention**

avec les dossiers récemment transmis aux agents.

---

# 9. SCÉNARIO INTERACTIF DE DÉMONSTRATION

Le frontend doit permettre de simuler le scénario complet de ma soutenance.

## Étape 1

Utilisateur :

> Bonjour, que peux-tu faire ?

## Étape 2

NGONI IA explique ses capacités.

## Étape 3

Utilisateur :

> J'ai une vidéo dans mes brouillons. Peux-tu la publier ?

## Étape 4

NGONI IA détecte l'action.

Afficher :

**Vidéo trouvée dans vos brouillons**

Bouton :

**Publier**

## Étape 5

Utilisateur confirme.

Afficher :

**Publication en cours...**

Puis :

**Vidéo publiée avec succès.**

## Étape 6

Afficher :

**Une vérification d'identité est requise pour poursuivre.**

## Étape 7

Simuler trois tentatives échouées.

Afficher :

**Tentative 1 — Échec**

**Tentative 2 — Échec**

**Tentative 3 — Échec**

## Étape 8

Déclencher automatiquement :

**Escalade vers un conseiller**

## Étape 9

Générer le résumé automatiquement.

## Étape 10

Faire apparaître la conversation dans l'espace Agent.

## Étape 11

L'agent peut reprendre la conversation.

## Étape 12

L'administration voit l'escalade dans son dashboard.

---

# 10. FONCTIONNEMENT FRONTEND

Même si le backend réel n'est pas encore connecté, créer une architecture frontend permettant facilement de remplacer les données simulées par de vraies API.

Créer une couche de services séparée :

```text
services/
```

Prévoir des fonctions telles que :

```text
sendMessage()
publishVideo()
verifyIdentity()
escalateConversation()
getConversation()
getConversations()
getDashboardStats()
```

Pour l'instant, utiliser des données mockées réalistes si aucune API backend n'est disponible.

**Ne pas créer de fausses API externes.**

Le code doit être organisé de manière à pouvoir connecter ultérieurement les véritables endpoints FastAPI et microservices NGONI.

---

# 11. IMPORTANT — QUALITÉ VISUELLE

Ne te contente pas de créer trois pages fonctionnelles basiques.

Je veux un frontend visuellement travaillé.

À l'ouverture :

* interface immédiatement compréhensible ;
* hiérarchie visuelle évidente ;
* aucun élément inutile ;
* beaucoup d'espace ;
* excellente lisibilité ;
* composants cohérents ;
* transitions discrètes ;
* états interactifs réalistes.

Le résultat doit donner l'impression :

> **« Ceci est une vraie plateforme de support NGONI déjà utilisée par une entreprise. »**

---

# 12. RESPONSIVE

Le design principal doit être optimisé pour desktop, car il sera utilisé pendant une démonstration sur ordinateur.

Prévoir néanmoins une adaptation raisonnable pour :

* tablette ;
* écran plus petit.

---

# 13. RÈGLES STRICTES

Ne pas :

* inventer une nouvelle identité graphique ;
* utiliser une palette sans rapport avec l'image Support ;
* remplacer l'icône Support ;
* créer une esthétique cyberpunk ;
* utiliser des robots ;
* utiliser des cerveaux numériques ;
* surcharger les interfaces ;
* mettre des graphiques partout ;
* créer des fonctionnalités qui ne correspondent pas au scénario ;
* simplement afficher les images de référence.

Il faut **construire les interfaces à partir de zéro**.

---

# 14. LIVRABLE

Le résultat final doit contenir un dossier :

```text
frontfolder/
```

contenant l'intégralité du frontend.

Le projet doit pouvoir être lancé localement avec les commandes appropriées.

Fournir également un `README.md` expliquant :

* comment installer les dépendances ;
* comment lancer le frontend ;
* où modifier les données mockées ;
* où connecter les API backend ;
* comment accéder aux pages Chat, Agent et Admin.

Les trois interfaces doivent être fonctionnelles et navigables entre elles.

### Pages principales finales

```text
/chat
/agent
/admin
```

Créer un **véritable prototype frontend fonctionnel de NGONI IA**, et non une simple image ou une maquette statique.

L'image de l'icône Support sert de référence pour l'identité visuelle.

Les images Chat, Agent et Admin servent de références conceptuelles.

**Le code frontend complet doit être créé de zéro dans `frontfolder`.**
