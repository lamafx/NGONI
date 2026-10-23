"""Lance toute la pile NGONI (agent conversationnel) et la teste.

Equivalent Python de scripts\\demarrer-live.ps1, plus un test automatique de
l'agent et un mode discussion dans le terminal. Bibliotheque standard
uniquement : aucun `pip install` necessaire.

    python scripts\\lancer_ngoni.py                 # tout lancer, tester, ouvrir le chat
    python scripts\\lancer_ngoni.py --console       # ... puis discuter avec l'agent ici
    python scripts\\lancer_ngoni.py --entrainer     # reentrainer Rasa d'abord (apres un clone)
    python scripts\\lancer_ngoni.py --verifier      # verifier + tester, puis rendre la main
    python scripts\\lancer_ngoni.py --arreter       # arreter ce qui a ete lance

Ordre de demarrage (le meme que le script PowerShell) :
    PostgreSQL -> Ollama -> Docker -> Rasa + actions -> FastAPI + stubs -> Vite
FastAPI attend que Rasa reponde avant de finir son demarrage, d'ou cet ordre.

Ctrl+C arrete UNIQUEMENT ce que ce script a lui-meme demarre : un service
deja en marche avant (port deja ouvert) est laisse tel quel.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
FASTAPI = RACINE / "fastapi"
FRONTEND = RACINE / "frontend"
PYTHON_VENV = FASTAPI / ".venv" / "Scripts" / "python.exe"
# Meme dossier et meme fichier de PIDs que demarrer-live.ps1 : arreter-live.ps1
# sait donc aussi arreter ce que ce script a lance, et inversement.
ETAT = Path(tempfile.gettempdir()) / "ngoni-live"
FICHIER_PIDS = ETAT / "pids.txt"

RASA = "http://localhost:5005"
ACTIONS = "http://localhost:5055"
MOTEUR = "http://127.0.0.1:8000"
OLLAMA = "http://localhost:11434"
CHAT_URL = "http://localhost:5173/#/chat"
MODELES_OLLAMA = ("qwen3:1.7b", "qwen3-embedding:0.6b")
# Sans GPU, Rasa met plusieurs minutes a charger ses politiques TensorFlow
# (mesure : ~8 min sur cette machine) -- d'ou une attente genereuse.
ATTENTE_RASA_S = 900

# Couleurs ANSI (activees sous Windows 10+ par l'appel os.system("") ci-dessous).
VERT, ROUGE, JAUNE, CYAN, GRIS, FIN = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[90m", "\033[0m"

bilan: list[tuple[str, bool, str]] = []
lances: list[tuple[str, subprocess.Popen]] = []
conteneurs_lances = False


# --------------------------------------------------------------------------- outils

def etape(texte: str) -> None:
    print(f"\n{CYAN}== {texte}{FIN}", flush=True)


def noter(service: str, ok: bool, detail: str = "") -> None:
    bilan.append((service, ok, detail))
    couleur, etat = (VERT, "OK    ") if ok else (ROUGE, "ECHEC ")
    print(f"   {couleur}{etat}{FIN} {service}  {GRIS}{detail}{FIN}", flush=True)


def info(texte: str) -> None:
    print(f"   {GRIS}{texte}{FIN}", flush=True)


def port_ouvert(port: int) -> bool:
    # IPv4 ET IPv6 : Vite n'ecoute que sur [::1] (constate : 127.0.0.1:5173
    # ferme alors que le frontend tournait), FastAPI/stubs sur 127.0.0.1.
    for famille, hote in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(famille, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex((hote, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def http(url: str, corps: dict | None = None, timeout: float = 10) -> tuple[int, object]:
    """GET (ou POST JSON si `corps`) -> (statut, JSON ou texte). Statut 0 si injoignable."""
    data = json.dumps(corps).encode("utf-8") if corps is not None else None
    requete = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            brut = reponse.read().decode("utf-8", errors="replace")
            statut = reponse.status
    except urllib.error.HTTPError as erreur:
        return erreur.code, erreur.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, None
    try:
        return statut, json.loads(brut)
    except ValueError:
        return statut, brut


def attendre(url: str, secondes: int, condition=lambda statut, corps: 0 < statut < 500) -> bool:
    fin = time.time() + secondes
    while time.time() < fin:
        statut, corps = http(url, timeout=5)
        if condition(statut, corps):
            return True
        time.sleep(3)
    return False


def lancer(nom: str, commande: list[str], dossier: Path) -> subprocess.Popen:
    """Processus en arriere-plan, sans fenetre, journal dans %TEMP%\\ngoni-live."""
    ETAT.mkdir(parents=True, exist_ok=True)
    journal = open(ETAT / f"{nom}.log", "w", encoding="utf-8", errors="replace")
    processus = subprocess.Popen(
        commande, cwd=dossier, stdout=journal, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lances.append((nom, processus))
    with open(FICHIER_PIDS, "a", encoding="utf-8") as f:
        f.write(f"{nom}={processus.pid}\n")
    return processus


def tuer(pid: int) -> None:
    # /T : Vite tourne sous cmd.exe -> npx -> node, il faut tout l'arbre.
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def docker(*arguments: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *arguments], cwd=RACINE, capture_output=True, text=True, timeout=timeout)


def docker_pret() -> bool:
    try:
        resultat = docker("info", "--format", "{{.ServerVersion}}", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return resultat.returncode == 0 and bool(resultat.stdout.strip())


# --------------------------------------------------------------------------- etapes

def verifier_prerequis() -> bool:
    etape("0/7  Prerequis")
    ok = True
    if not PYTHON_VENV.exists():
        noter("venv FastAPI", False, f"absent : {PYTHON_VENV} -- voir utils.txt §0 (python -m venv .venv)")
        ok = False
    else:
        noter("venv FastAPI", True, str(PYTHON_VENV))
    if not (FRONTEND / "node_modules").exists():
        info("frontend/node_modules absent -> npm install (une seule fois, 1 a 3 min)...")
        resultat = subprocess.run("npm install", cwd=FRONTEND, shell=True, capture_output=True, text=True)
        noter("npm install", resultat.returncode == 0, "" if resultat.returncode == 0 else resultat.stderr[-300:])
        ok = ok and resultat.returncode == 0
    for chemin in (RACINE / "rasa" / ".env", RACINE / "rasa" / "actions" / ".env", FASTAPI / ".env"):
        if not chemin.exists():
            noter(str(chemin.relative_to(RACINE)), False, "absent -- copier le .env.example voisin et le remplir")
            ok = False
    return ok


def postgres() -> None:
    etape("1/7  PostgreSQL (:5432)")
    ouvert = port_ouvert(5432)
    noter("PostgreSQL", ouvert, "port 5432 ouvert" if ouvert else
          "demarrer le service Windows : Start-Service postgresql-x64-17 (PowerShell admin)")


def ollama() -> bool:
    etape("2/7  Ollama (:11434)")
    if not attendre(f"{OLLAMA}/api/version", 2):
        executable = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        info("Ollama arrete -> demarrage")
        try:
            subprocess.Popen([str(executable), "serve"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as erreur:
            noter("Ollama", False, f"impossible de lancer {executable} : {erreur}")
            return False
    if not attendre(f"{OLLAMA}/api/version", 30):
        noter("Ollama", False, "ne repond pas sur :11434")
        return False
    _, tags = http(f"{OLLAMA}/api/tags")
    presents = {m.get("name") for m in (tags or {}).get("models", [])} if isinstance(tags, dict) else set()
    manquants = [m for m in MODELES_OLLAMA if m not in presents]
    noter("Ollama", not manquants, "modeles manquants : " + ", ".join(f"ollama pull {m}" for m in manquants)
          if manquants else " + ".join(MODELES_OLLAMA))
    return not manquants


def docker_desktop() -> bool:
    etape("3/7  Docker Desktop")
    if not docker_pret():
        info("Docker arrete -> demarrage de Docker Desktop (1 a 3 min)")
        try:
            subprocess.Popen([r"C:\Program Files\Docker\Docker\Docker Desktop.exe"])
        except OSError as erreur:
            noter("Docker", False, f"impossible de lancer Docker Desktop : {erreur}")
            return False
        fin = time.time() + 240
        while not docker_pret() and time.time() < fin:
            time.sleep(5)
    ok = docker_pret()
    noter("Docker", ok, "moteur pret" if ok else "Docker Desktop ne repond pas")
    return ok


def rasa(entrainer: bool) -> bool:
    global conteneurs_lances
    etape("4/7  Rasa (:5005) + serveur d'actions (:5055)")
    if entrainer:
        info("Entrainement du modele Rasa (plusieurs minutes)...")
        resultat = docker("compose", "run", "--rm", "rasa", "python", "-m", "rasa", "train", "--out", "models",
                          timeout=3600)
        noter("Entrainement Rasa", resultat.returncode == 0, "" if resultat.returncode == 0 else resultat.stderr[-300:])
        if resultat.returncode != 0:
            return False
    deja = port_ouvert(5005) and port_ouvert(5055)
    resultat = docker("compose", "up", "-d", "rasa", "actions")
    if resultat.returncode != 0:
        noter("docker compose up", False, resultat.stderr[-300:])
        return False
    conteneurs_lances = not deja
    info(f"chargement du modele Rasa (jusqu'a {ATTENTE_RASA_S // 60} min sans GPU)...")
    # /status ne contient "model_file" qu'une fois le modele charge.
    rasa_ok = attendre(f"{RASA}/status", ATTENTE_RASA_S,
                       lambda statut, corps: statut == 200 and isinstance(corps, dict) and "model_file" in corps)
    _, statut = http(f"{RASA}/status")
    noter("Rasa", rasa_ok, f"modele : {statut.get('model_file')}" if rasa_ok and isinstance(statut, dict)
          else "voir : docker compose logs rasa")
    actions_ok = attendre(f"{ACTIONS}/health", 120)
    noter("Actions", actions_ok, "serveur d'actions pret" if actions_ok else "voir : docker compose logs actions")
    return rasa_ok and actions_ok


def moteur_et_stubs() -> bool:
    etape("5/7  Moteur FastAPI (:8000) + stubs wallet (:3103) / user (:3104)")
    tout_ok = True
    for nom, module, port in (("fastapi", "app.main:app", 8000),
                              ("wallet_stub", "wallet_stub.main:app", 3103),
                              ("user_stub", "user_stub.main:app", 3104)):
        if port_ouvert(port):
            info(f"{nom} deja en ecoute sur :{port}")
        else:
            lancer(nom, [str(PYTHON_VENV), "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)],
                   FASTAPI)
        # FastAPI precharge les embeddings et attend Rasa avant d'ouvrir son port.
        ok = attendre(f"http://127.0.0.1:{port}/docs", 300 if nom == "fastapi" else 90)
        noter(nom, ok, f"http://127.0.0.1:{port}" if ok else f"journal : {ETAT / (nom + '.log')}")
        tout_ok = tout_ok and ok
    return tout_ok


def frontend() -> bool:
    etape("6/7  Interface web Vite (:5173)")
    if port_ouvert(5173):
        info("frontend deja en ecoute sur :5173")
    else:
        lancer("frontend", ["cmd.exe", "/c", "npx --no-install vite --port 5173 --strictPort"], FRONTEND)
    ok = attendre("http://localhost:5173/", 90)
    noter("Frontend", ok, "http://localhost:5173" if ok else f"journal : {ETAT / 'frontend.log'}")
    return ok


def prechauffage() -> None:
    etape("7/7  Prechauffage des modeles (1 a 3 min sans GPU)")
    debut = time.time()
    statut, _ = http(f"{MOTEUR}/embeddings/query", {"text": "bonjour"}, timeout=180)
    noter("Embeddings", statut == 200, f"{time.time() - debut:.0f} s")
    # Deux passages : le premier charge qwen3:1.7b, le second part du regime normal.
    for phrase in ("Bonjour", "Combien de temps prend un retrait ?"):
        debut = time.time()
        statut, corps = http(f"{RASA}/model/parse", {"text": phrase}, timeout=300)
        intention = (corps or {}).get("intent", {}).get("name") if isinstance(corps, dict) else None
        noter(f"NLU '{phrase}'", bool(intention) and intention != "nlu_fallback",
              f"{intention} ({time.time() - debut:.0f} s)")
    statut, corps = http(f"{MOTEUR}/conversations/memory?user_id=prechauffage", timeout=30)
    noter("Memoire conversations", statut == 200, "endpoint pret" if statut == 200 else f"HTTP {statut}")


# --------------------------------------------------------------------------- test de l'agent

def parler(sender: str, texte: str, user_id: str) -> tuple[list[dict], float]:
    """Un tour de dialogue, comme le frontend : webhook Rasa avec metadata.user_id."""
    debut = time.time()
    statut, corps = http(f"{RASA}/webhooks/rest/webhook",
                         {"sender": sender, "message": texte, "metadata": {"user_id": user_id}}, timeout=180)
    return (corps if statut == 200 and isinstance(corps, list) else []), time.time() - debut


def afficher_reponses(messages: list[dict], duree: float) -> None:
    if not messages:
        print(f"   {ROUGE}(aucune reponse){FIN}")
    for message in messages:
        texte = " ".join((message.get("text") or "").split())
        print(f"   {VERT}Agent :{FIN} {texte}")
        boutons = [b.get("title") for b in message.get("buttons") or []]
        if boutons:
            print(f"   {GRIS}[ {' | '.join(boutons)} ]{FIN}")
    print(f"   {GRIS}({duree:.1f} s){FIN}", flush=True)


def tester_agent() -> None:
    etape("Test de l'agent (vraie conversation, vrais services)")
    sender = f"test-lanceur-{uuid.uuid4().hex[:6]}"
    user_id = f"test-lanceur-{uuid.uuid4().hex[:6]}"
    reussis = 0
    # Accueil, question FAQ couverte par le catalogue, hors-sujet.
    scenario = ("bonjour", "Combien de temps prend un retrait ?", "qui va gagner la CAN ?")
    for texte in scenario:
        print(f"\n   {JAUNE}Vous :{FIN} {texte}", flush=True)
        messages, duree = parler(sender, texte, user_id)
        afficher_reponses(messages, duree)
        reussis += bool(messages)
    noter("Test de l'agent", reussis == len(scenario), f"{reussis}/{len(scenario)} messages ont obtenu une reponse")


def console() -> None:
    etape("Discussion avec l'agent dans le terminal (ligne vide ou 'quitter' pour sortir)")
    print(f"   {GRIS}Sans GPU, comptez 10 a 20 s par reponse.{FIN}")
    sender = f"console-{uuid.uuid4().hex[:6]}"
    user_id = "console-utilisateur"  # stable : l'agent se souvient d'une session console a l'autre
    while True:
        try:
            texte = input(f"\n{JAUNE}Vous : {FIN}").strip()
        except EOFError:
            break
        if not texte or texte.lower() in ("quitter", "exit", "q"):
            break
        afficher_reponses(*parler(sender, texte, user_id))


# --------------------------------------------------------------------------- arret

def arreter_ce_qui_a_ete_lance() -> None:
    print(f"\n{CYAN}== Arret{FIN}")
    for nom, processus in reversed(lances):
        tuer(processus.pid)
        info(f"arrete : {nom} (pid {processus.pid})")
    if conteneurs_lances:
        docker("compose", "stop", "rasa", "actions")
        info("arrete : conteneurs rasa + actions")
    if FICHIER_PIDS.exists():
        FICHIER_PIDS.unlink()
    print(f"{VERT}Termine.{FIN} PostgreSQL, Ollama et Docker Desktop restent en marche.")


def arreter_tout() -> None:
    """--arreter : comme scripts\\arreter-live.ps1."""
    if FICHIER_PIDS.exists():
        for ligne in FICHIER_PIDS.read_text(encoding="utf-8").splitlines():
            if "=" in ligne:
                nom, pid = ligne.split("=", 1)
                tuer(int(pid))
                print(f"   arrete : {nom} (pid {pid})")
        FICHIER_PIDS.unlink()
    else:
        print("   aucun processus enregistre par le lanceur")
    docker("compose", "stop", "rasa", "actions")
    print(f"{VERT}Pile NGONI arretee.{FIN}")


# --------------------------------------------------------------------------- main

def main() -> int:
    os.system("")  # active les couleurs ANSI dans la console Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Lance et teste la pile NGONI (agent conversationnel).")
    parser.add_argument("--entrainer", action="store_true", help="reentrainer le modele Rasa avant de demarrer")
    parser.add_argument("--console", action="store_true", help="discuter avec l'agent dans le terminal")
    parser.add_argument("--verifier", action="store_true", help="verifier + tester puis rendre la main (tout reste lance)")
    parser.add_argument("--sans-prechauffage", action="store_true", help="sauter le prechauffage des modeles")
    parser.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le chat dans le navigateur")
    parser.add_argument("--arreter", action="store_true", help="arreter ce que le lanceur a demarre, puis quitter")
    args = parser.parse_args()

    if args.arreter:
        arreter_tout()
        return 0

    ETAT.mkdir(parents=True, exist_ok=True)
    try:
        if not verifier_prerequis():
            print(f"\n{ROUGE}Prerequis manquants, voir ci-dessus.{FIN}")
            return 1
        postgres()
        ollama()
        if not docker_desktop():
            print(f"{ROUGE}Impossible de continuer sans Docker.{FIN}")
            return 1
        if not rasa(args.entrainer):
            print(f"{ROUGE}Rasa n'a pas demarre : FastAPI l'attend, inutile de continuer.{FIN}")
            return 1
        moteur_et_stubs()
        frontend()
        if not args.sans_prechauffage:
            prechauffage()
        tester_agent()

        etape("Bilan")
        echecs = [b for b in bilan if not b[1]]
        for service, ok, detail in bilan:
            print(f"   {(VERT + 'OK   ') if ok else (ROUGE + 'ECHEC')}{FIN} {service:<38} {GRIS}{detail}{FIN}")
        print(f"\n{VERT}Tout est pret.{FIN}" if not echecs else
              f"\n{ROUGE}{len(echecs)} point(s) en echec -- a corriger avant le passage.{FIN}")
        print(f"\n   Chat client        : {CHAT_URL}")
        print("   Espace conseiller  : http://localhost:5173/#/agent")
        print("   Administration     : http://localhost:5173/#/admin")
        print(f"   Journaux           : {ETAT}")

        if not args.sans_navigateur:
            webbrowser.open(CHAT_URL)
        if args.console:
            console()
        if args.verifier:
            print(f"\n{GRIS}--verifier : tout reste lance. Pour arreter : python scripts\\lancer_ngoni.py --arreter{FIN}")
            return 0 if not echecs else 1
        if not args.console:
            print(f"\n{JAUNE}Ctrl+C pour tout arreter.{FIN}", flush=True)
            while True:
                time.sleep(1)
        arreter_ce_qui_a_ete_lance()
        return 0
    except KeyboardInterrupt:
        arreter_ce_qui_a_ete_lance()
        return 0


if __name__ == "__main__":
    sys.exit(main())
