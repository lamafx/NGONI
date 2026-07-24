"""Recalcule embedding = embed_passage(question) pour toutes les lignes de
ia.faq_items avec le modele d'embedding COURANT (app.shared.embeddings).

A executer une seule fois apres un changement de modele d'embedding (voir
migrations/0001_e5_base_upgrade.sql, etape 2) -- deux vecteurs ne sont
comparables que s'ils viennent du meme modele, un changement de modele exige
donc de tout recalculer, pas seulement les nouveaux items.

Lancement :
    cd fastapi
    .venv\\Scripts\\python.exe scripts\\reembed_faq.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Execute directement par chemin (python scripts\reembed_faq.py), pas comme
# module -- sys.path[0] devient alors le dossier du script (fastapi/scripts/)
# et non fastapi/, ou vit le package `app`. L'ajouter explicitement evite de
# devoir positionner PYTHONPATH/cwd a la main a chaque lancement.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.domains.faq.repository import FaqRepository
from app.shared.embeddings import embed_passage


def main() -> None:
    session = SessionLocal()
    try:
        repository = FaqRepository(session)
        items = repository.list_all()
        total = len(items)
        if total == 0:
            print("Aucune ligne dans ia.faq_items, rien a faire.")
            return
        for index, item in enumerate(items, start=1):
            embedding = embed_passage(item.question)
            repository.update_embedding(item, embedding)
            print(f"[{index}/{total}] recalcule : {item.question!r}")
        print(f"Termine : {total} ligne(s) recalculee(s).")
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
