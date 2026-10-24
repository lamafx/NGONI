# Installer NGONI ia-service sur un autre PC

Deux scripts, chacun à lancer par un double-clic :

| Script | PC | Rôle |
|---|---|---|
| `PREPARER-TRANSFERT.cmd` | **ancien** PC | prépare le dossier `NGONI-installation` à emporter |
| `INSTALLER.cmd` | **nouveau** PC | installe les outils, récupère le code, restaure la base et les volumes, lance tout |

## 1. Sur l'ancien PC : préparer le dossier

1. Démarrer la pile si elle est arrêtée : `docker compose up -d` (l'export de la base passe par le conteneur postgres).
2. Vérifier que tout est poussé sur GitHub (`git status`, `git push`). Le script signale sinon les commits manquants.
3. Double-cliquer sur `installation\PREPARER-TRANSFERT.cmd`.

Il crée `C:\DEV\NGONI\NGONI-installation\` :

```
NGONI-installation\
  INSTALLER.cmd, installer.ps1, README.md
  fichiers\   .env (x4) et docker\postgres\chatbotdb.dump  ← export frais de la base
  volumes\    pfe_ollama.tar.gz                             ← modèles qwen3 (~2 Go)
```

Le volume des modèles n'est archivé que s'il y a au moins 4 Go libres. Sinon, le nouveau PC les télécharge (~2 Go). Pour écrire directement sur une clé USB, ce qui est recommandé, lancer depuis un terminal :

```
installation\PREPARER-TRANSFERT.cmd -Sortie E:\NGONI-installation
```

`-SansModeles` saute l'archive des modèles.

> **Ce dossier contient les mots de passe (`.env`) et des données réelles (conversations, KYC).** Le transporter sur une clé USB ou un Drive privé. Ne jamais le mettre sur GitHub.

## 2. Sur le nouveau PC : installer et lancer

1. Copier le dossier `NGONI-installation` n'importe où (bureau, clé USB…).
2. Double-cliquer sur `INSTALLER.cmd`.

Le script enchaîne :

1. **Outils** : installe Git, WSL et Docker Desktop via `winget` s'ils manquent. Windows demande l'autorisation administrateur.
   → Après l'installation de Docker ou de WSL, **redémarrer le PC et double-cliquer à nouveau** sur `INSTALLER.cmd`. Au premier démarrage, Docker Desktop demande d'accepter ses conditions.
2. **Code** : clone `https://github.com/lamafx/NGONI.git` (branche `opt-embedding`) dans `C:\DEV\NGONI\ngoni-ia-service`, ou le met à jour s'il est déjà là. Si le dépôt est privé, une fenêtre de connexion GitHub s'ouvre.
3. **Fichiers hors dépôt** : copie `fichiers\` dans le projet (`.env`, export de la base).
4. **Volumes** : recrée chaque volume de `volumes\` (`pfe_ollama`). Un volume qui existe déjà est conservé.
5. **Lancement** : `docker compose up -d --build`, attente de la fin du préchauffage du modèle, puis ouverture de http://localhost:5173.

Au premier lancement, la base est **restaurée automatiquement** depuis `docker\postgres\chatbotdb.dump`, et le modèle Rasa est fourni par le dépôt.

**Durée** : 20 à 40 min la première fois. C'est surtout du téléchargement : images Docker, dépendances Python et npm, modèle spaCy, et les modèles qwen3 s'ils n'ont pas été archivés. Les lancements suivants prennent quelques minutes.

Le script peut être relancé autant de fois que nécessaire : il saute ce qui est déjà fait. Son journal est dans `NGONI-installation\installation.log`.

Prévoir **~25 Go libres**. Dans Docker Desktop > Settings > Resources : 8 Go de mémoire et 4 cœurs au minimum.

## Ensuite

```
cd C:\DEV\NGONI\ngoni-ia-service
docker compose up -d      # démarrer
docker compose down       # arrêter (les données sont conservées)
```

Ne **jamais** lancer `docker compose down -v` sans sauvegarde : `-v` efface la base et les modèles.

## Depuis un simple clone (le plus simple)

Depuis le 2026-10-24, les `.env` (mots de passe de test) et `docker/postgres/chatbotdb.dump` sont versionnés. Un clone suffit donc, sans dossier de transfert :

```
git clone -b opt-embedding https://github.com/lamafx/NGONI.git C:\DEV\NGONI\ngoni-ia-service
```

puis double-clic sur `C:\DEV\NGONI\ngoni-ia-service\installation\INSTALLER.cmd`. Seuls les modèles qwen3 (volume `pfe_ollama`) sont téléchargés au lieu d'être copiés.

## En cas de problème

| Symptôme | Que faire |
|---|---|
| « Docker ne répond pas après 5 min » | Ouvrir Docker Desktop, accepter les conditions, attendre « Engine running », relancer `INSTALLER.cmd` |
| « winget absent » | Installer « App Installer » depuis le Microsoft Store, ou Git et Docker Desktop à la main |
| Le préchauffage échoue | Relancer `INSTALLER.cmd`. Sinon : `docker compose logs rasa fastapi` |
| Port 5173, 8000 ou 5433 déjà pris | Arrêter le programme qui l'occupe, ou changer le port dans `docker-compose.yml` / `.env` |
