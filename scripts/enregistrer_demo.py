"""Enregistre la video de demonstration (mode ?demo=1), coupee automatiquement.

    python scripts\\enregistrer_demo.py
    python scripts\\enregistrer_demo.py --journal C:\\chemin\\vers\\fastapi.log

Ce que fait le script :
  1. affiche les consignes et attend Entree ;
  2. filme l'ecran (ffmpeg gdigrab, 1920x1080, 30 i/s, comme demo-ngoni.mp4) ;
  3. ouvre la demo dans Chrome en plein ecran (profil separe) ;
  4. repere le DEBUT et la FIN de la demo dans le journal du moteur FastAPI :
       debut = la demo remet les seuils a zero (GET /admin/settings/parameters)
       fin   = la derniere scene ecrit le seuil (PUT /admin/settings/parameters/<id>),
               + le temps de lecture du journal des modifications ;
  5. s'arrete tout seul, coupe avant/apres, et ecrit demo\\demo-ngoni-v2.mp4
     (l'ancienne video n'est jamais ecrasee).

L'envoi de la piece d'identite reste MANUEL, comme avant : la demo se met en
pause, le bouton « Joignez votre piece d'identite » ouvre le gestionnaire de
fichiers Windows, on choisit la piece, on l'envoie, la demo reprend.

Bibliotheque standard uniquement. Necessite ffmpeg dans le PATH et Chrome.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE_DEFAUT = RACINE / "demo" / "demo-ngoni-v2.mp4"
PIECE = RACINE / "demo" / "carteIDFront.png"
URL_DEMO = "http://localhost:5173/?demo=1#/chat"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# Journaux possibles du moteur : lancer_ngoni.py (stdout+stderr) et
# demarrer-live.ps1 (les acces uvicorn sortent sur stdout -> .log).
JOURNAUX = [
    Path(tempfile.gettempdir()) / "ngoni-live" / "fastapi.log",
    Path(tempfile.gettempdir()) / "ngoni-live" / "fastapi.log.err",
]
DEBUT = re.compile(r'"GET /admin/settings/parameters HTTP')
FIN = re.compile(r'"(PUT|PATCH|POST) /admin/settings/parameters/(?!history)[^ ]+ HTTP')

# Apres l'ecriture du seuil, la scene dure encore : 0,8 s (apres confirmation)
# + 0,9 (descente vers le journal) + 0,55 (curseur) + 1,6 (incrustation
# « modification tracee ») + 2,4 (lecture) = 6,25 s -- voir DEMO_ADMIN_ACT.settings.
APRES_FIN_S = 7.5
AVANT_DEBUT_S = 1.2


def choisir_journal(explicite: str | None) -> Path | None:
    if explicite:
        return Path(explicite)
    existants = [p for p in JOURNAUX if p.exists()]
    return max(existants, key=lambda p: p.stat().st_mtime) if existants else None


def duree(fichier: Path) -> float:
    sortie = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(fichier)],
        capture_output=True, text=True,
    )
    try:
        return float(sortie.stdout.strip())
    except ValueError:
        return 0.0


def main() -> int:
    os.system("")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Enregistre la video de demonstration NGONI.")
    parser.add_argument("--journal", help="journal du moteur FastAPI (sinon detection automatique)")
    parser.add_argument("--sortie", default=str(SORTIE_DEFAUT), help="fichier video final")
    parser.add_argument("--duree-max", type=int, default=480, help="arret de securite, en secondes")
    parser.add_argument("--sans-navigateur", action="store_true", help="(test) ne pas ouvrir Chrome")
    parser.add_argument("--sans-attente", action="store_true", help="(test) ne pas attendre Entree")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        print("ffmpeg introuvable dans le PATH.")
        return 1
    journal = choisir_journal(args.journal)
    if journal is None or not journal.exists():
        print("Journal du moteur FastAPI introuvable : lancez la pile avec scripts\\lancer_ngoni.py,")
        print("ou indiquez-le avec --journal. Sans lui, la coupe automatique est impossible.")
        return 1

    sortie = Path(args.sortie)
    brut = sortie.with_name(sortie.stem + "-brut.mp4")
    profil = Path(tempfile.gettempdir()) / "ngoni-chrome-demo"

    print("\n== Enregistrement de la demonstration NGONI ==\n")
    print("  Pendant l'enregistrement :")
    print("   1. Chrome s'ouvre en plein ecran sur la demo. Cliquez sur le bouton « Démo » (en haut).")
    print("   2. Quand la demo s'arrete, cliquez sur « Joignez votre pièce d'identité pour continuer » :")
    print("      votre gestionnaire de fichiers s'ouvre. Choisissez :")
    print(f"        {PIECE}")
    print("      puis cliquez sur le bouton d'envoi.")
    print("   3. Rangez la souris dans un coin de l'ecran et ne touchez plus a rien.")
    print("   4. L'enregistrement s'arrete TOUT SEUL a la fin (ecran Parametres, journal des modifications).")
    print("      Pour annuler : fermez Chrome (Alt+F4).")
    print("\n  Conseil : activez « Ne pas déranger » (pas de notification Windows dans la video).")
    if not args.sans_attente:
        input("\n  Appuyez sur Entree pour commencer...")

    taille_initiale = journal.stat().st_size
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "gdigrab", "-framerate", "30", "-draw_mouse", "1", "-i", "desktop",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p", str(brut)],
        stdin=subprocess.PIPE,
    )
    t0 = time.time()
    time.sleep(0.8)  # laisse ffmpeg ouvrir la capture avant que Chrome n'apparaisse

    chrome = None
    if not args.sans_navigateur:
        chrome = subprocess.Popen([str(CHROME), f"--user-data-dir={profil}", "--no-first-run",
                                   "--no-default-browser-check", "--start-fullscreen", f"--app={URL_DEMO}"])

    t_debut = t_fin = None
    position = taille_initiale
    motif = "securite"
    while time.time() - t0 < args.duree_max:
        time.sleep(0.25)
        with open(journal, "r", encoding="utf-8", errors="replace") as f:
            f.seek(position)
            nouveau = f.read()
            position = f.tell()
        for ligne in nouveau.splitlines():
            if t_debut is None and DEBUT.search(ligne):
                t_debut = time.time() - t0
                print(f"  -> debut de la demo detecte ({t_debut:.1f} s)", flush=True)
            elif t_debut is not None and t_fin is None and FIN.search(ligne):
                t_fin = time.time() - t0
                print(f"  -> derniere scene detectee ({t_fin:.1f} s)", flush=True)
        if t_fin is not None and time.time() - t0 >= t_fin + APRES_FIN_S + 0.5:
            motif = "fin de la demo"
            break
        if chrome is not None and chrome.poll() is not None:
            motif = "Chrome ferme"
            break

    ffmpeg.communicate(b"q")
    if chrome is not None and chrome.poll() is None:
        subprocess.run(["taskkill", "/PID", str(chrome.pid), "/T", "/F"], capture_output=True)
    print(f"\n  Enregistrement arrete ({motif}). Brut : {brut} ({duree(brut):.0f} s)")

    if t_debut is None or t_fin is None:
        print("  Debut ou fin de la demo non detecte : le brut est conserve tel quel, sans coupe.")
        return 1

    debut = max(0.0, t_debut - AVANT_DEBUT_S)
    fin = t_fin + APRES_FIN_S
    print(f"  Coupe de {debut:.1f} s a {fin:.1f} s, encodage final...")
    resultat = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{debut:.2f}", "-to", f"{fin:.2f}", "-i", str(brut),
         "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-r", "30", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", "-an", str(sortie)],
    )
    if resultat.returncode != 0:
        print("  Echec de l'encodage final ; le brut est conserve.")
        return 1
    d = duree(sortie)
    print(f"\n  Video prete : {sortie}  ({int(d // 60)}:{int(d % 60):02d})")
    print(f"  (le brut non coupe reste disponible : {brut})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
