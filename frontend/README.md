# NGONI IA — Frontend de démonstration

Prototype frontend (React + Vite, JSX) des trois interfaces du
support intelligent NGONI : **Chat utilisateur**, **Espace agent humain** et
**Administration**. Le chat est **branché sur le vrai serveur Rasa** pour
tout ce qui relève de la compréhension du langage (FAQ, diagnostic,
capacités, accueil...) ; seul le scénario "publication de vidéo" reste
simulé, faute d'équivalent dans le moteur actuel (voir plus bas).

## Installer

```bash
cd frontfolder
npm install
```

## Lancer en développement

**1. Démarrer Rasa** (depuis la racine du dépôt principal, pas
`frontfolder/`) :

```bash
docker compose up -d rasa actions
```

Vérifier que le modèle est chargé : <http://localhost:5005/status> doit
répondre. Sans `actions` démarré, Rasa répond mais toute action
personnalisée (diagnostic, FAQ, capacités dynamiques...) échoue en silence
côté conversation — les deux conteneurs sont nécessaires.

**2. Démarrer le frontend** :

```bash
cd frontfolder
npm run dev
```

Ouvre <http://localhost:5173>. En développement, les requêtes vers Rasa
passent par le proxy du serveur Vite (`/rasa` → `http://localhost:5005`,
voir `vite.config.js`) pour éviter tout problème de CORS — Rasa lui-même
n'a besoin d'aucune configuration supplémentaire.

Si Rasa n'est pas joignable, le chat le signale clairement dans la
conversation plutôt que de planter (voir `chatService.js::sendMessage`).

| Page | Route |
|---|---|
| Chat utilisateur | `/chat` |
| Espace agent | `/agent` |
| Administration | `/admin` |

Un petit point discret en bas à gauche de chaque page (`src/components/layout/DiscreetSwitcher.jsx`)
ouvre un menu pour basculer vers les deux autres interfaces ou réinitialiser
le scénario — volontairement peu visible pour ne pas casser l'illusion d'un
vrai produit pendant une présentation.

## Scénario de démonstration

Sur `/chat`, tape :

1. Une vraie question — « Comment fonctionne le parrainage ? », « mon
   compte est bloqué », « que sais-tu faire ? »... — répond **le vrai Rasa**
   (NLU + Core + serveur d'actions), pas un mock.
2. « J'ai une vidéo dans mes brouillons, peux-tu la publier ? » → intercepté
   localement (aucune intention réelle ne couvre ce domaine, voir plus bas)
   → bouton **Publier la vidéo** → publication simulée → vérification
   d'identité demandée.
3. **Vérifier mon identité** échoue volontairement 3 fois de suite (comportement
   simulé, voir `src/services/chatService.js::verifyIdentity`) puis
   escalade automatiquement vers un conseiller : un ticket `CMP-…` est créé.
4. Bascule sur `/agent` : la conversation apparaît dans les escalades, avec
   le résumé généré et la chronologie complète.
5. Bascule sur `/admin` : le compteur « Demandes escaladées » et la liste
   « Escalades nécessitant une intervention » reflètent le même événement.

Les trois pages partagent un seul magasin d'état en mémoire
(`src/state/DemoStore.jsx`), persisté dans le `localStorage` du navigateur
pour survivre à un rechargement de page pendant une démonstration.

## Où modifier les données simulées

- `src/data/mockData.js` — conversations, tickets, agents et statistiques de
  départ.
- `src/services/chatService.js` — déclencheur local du scénario vidéo,
  échec de vérification volontaire.
- `src/services/dashboardService.js` — statistiques du tableau de bord admin.

## Branchement backend — état réel

| Fonction | État |
|---|---|
| `sendMessage()` | **Branchée** sur `POST /webhooks/rest/webhook` (Rasa réel) via `src/services/rasaClient.js`. Le déclencheur du scénario vidéo reste intercepté localement avant d'atteindre Rasa. |
| `getConversation(s)()` | Toujours locale (liste de conversations = bookkeeping propre à ce prototype, pas une notion exposée par Rasa) |
| `escalateConversation()` | Toujours simulée — à remplacer par `POST /tickets/create` (moteur FastAPI) quand le domaine vidéo existera côté backend |
| `getDashboardStats()` | Toujours simulée — `DiagnosticSession`/`DiagnosticAuditLog` fournissent déjà la donnée agrégée nécessaire côté moteur (voir `docs/12-logs-supervision.md` du dépôt principal, section « Limites actuelles de supervision ») |

`publishVideo()` et `verifyIdentity()` n'ont pas d'équivalent dans le
périmètre actuel du moteur (diagnostic wallet/user uniquement, pas de
domaine vidéo) — voir `docs/14-evolutions.md` du dépôt principal,
§14.6 « Nouveaux domaines diagnosticables ». Elles restent simulées tant que
ce domaine n'existe pas côté backend.

### Build de production et déploiement

Le proxy `/rasa` de `vite.config.js` n'existe qu'en développement
(`npm run dev`). Pour un `npm run build` / `npm run preview`, ou un
déploiement, définir la variable d'environnement `VITE_RASA_URL` pour
pointer directement vers le serveur Rasa (ex. `https://rasa.ngoni.example`)
— et s'assurer que ce serveur autorise les requêtes cross-origin depuis
l'origine du frontend.

## Identité visuelle

Palette relevée directement sur les maquettes de référence
(`chat.jpeg`, `dashbord.jpeg`) : vert émeraude en couleur primaire (bouton
d'envoi, avatars, "IA" du logo, statuts positifs), corail en accent
secondaire (section active, notifications, statuts urgents/"en cours"),
fond et surfaces neutres gris clair — voir `src/styles/tokens.css`.
L'icône Support officielle (`src/assets/ngoni-support-icon.jpeg`) reste
l'avatar exclusif de NGONI IA (jamais recréé ni remplacé), conformément à
`instruction.md`. Composants partagés (boutons, badges, cartes, avatars,
bulles de message, timeline, tableaux) dans `src/styles/components.css`.

## Build de production

```bash
npm run build
npm run preview
```
