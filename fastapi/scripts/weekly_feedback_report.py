"""Boucle de feedback hebdomadaire (docs/16-audit-faq-nlu-2026-07.md 16.7,
docs/taches.txt P1 #5) : audit.agent_actions et feedback.response_ratings
journalisent deja chaque recherche FAQ (voir record_faq_lookup,
app/domains/audit/service.py) et chaque notation utile/pas utile (voir
ActionRecordResponseRating, rasa/actions/feedback.py) -- mais cette donnee
n'etait exploitee nulle part avant ce script. Deux sections :

1. Questions posees sans reponse FAQ trouvee (action_type='faq_answer_not_found'),
   triees par frequence -- des candidats naturels a de futurs exemples
   d'entrainement ask_faq ou de nouvelles entrees de catalogue.
2. Reponses notees "pas utile" (feedback.response_ratings, is_useful=false),
   avec le score de similarite de la recherche qui les a servies quand il
   est retrouvable -- pas de cle etrangere entre les deux tables (convention
   du projet, voir docs/15-modele-donnees.md), jointure heuristique sur le
   texte de la question et l'action la plus recente qui la precede.

Lancement :
    cd fastapi
    .venv\\Scripts\\python.exe scripts\\weekly_feedback_report.py [--days 7]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Execute directement par chemin (python scripts\weekly_feedback_report.py),
# pas comme module -- meme raison que reembed_faq.py (voir son docstring) :
# rend `app` importable sans devoir positionner PYTHONPATH/cwd a la main.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402


def _not_found_questions(session, since: datetime, limit: int = 20):
    # input_data/output_data sont JSONB (voir migrations/0006_agent_actions_audit.sql) --
    # ->> extrait le texte, lower() pour regrouper des variantes de casse
    # identiques par ailleurs (pas de normalisation plus poussee : le but est
    # un signal de frequence pour un humain, pas un dedoublonnage exact).
    rows = session.execute(
        text(
            """
            SELECT lower(trim(input_data->>'question')) AS question, count(*) AS occurrences
            FROM audit.agent_actions
            WHERE domain = 'faq'
              AND action_type = 'faq_answer_not_found'
              AND created_at >= :since
              AND input_data->>'question' IS NOT NULL
            GROUP BY lower(trim(input_data->>'question'))
            ORDER BY occurrences DESC, question
            LIMIT :limit
            """
        ),
        {"since": since, "limit": limit},
    ).all()
    return [(row.question, row.occurrences) for row in rows]


def _not_useful_ratings_with_score(session, since: datetime, limit: int = 20):
    ratings = session.execute(
        text(
            """
            SELECT question, answer, created_at
            FROM feedback.response_ratings
            WHERE interaction_type = 'faq'
              AND is_useful = false
              AND created_at >= :since
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"since": since, "limit": limit},
    ).all()

    results = []
    for rating in ratings:
        # Jointure heuristique (pas de FK, voir docstring du module) : la
        # derniere recherche FAQ servie AVANT cette notation, sur exactement
        # la meme question -- au plus une correspondance exploitable, mais
        # "aucune trouvee" reste un resultat legitime (log absent/rotate,
        # question reformulee entre la reponse et la notation).
        served = session.execute(
            text(
                """
                SELECT output_data->>'score' AS score
                FROM audit.agent_actions
                WHERE domain = 'faq'
                  AND action_type = 'faq_answer_served'
                  AND lower(trim(input_data->>'question')) = lower(trim(:question))
                  AND created_at <= :rated_at
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"question": rating.question, "rated_at": rating.created_at},
        ).first()
        results.append((rating.question, rating.answer, served.score if served else None))
    return results


def main() -> None:
    # La console Windows par defaut encode en cp1252, incapable de
    # representer certains caracteres reellement presents dans les questions
    # journalisees (emojis, notamment) -- plante sinon avec un
    # UnicodeEncodeError des le premier print, constate en conditions
    # reelles sur ce depot. errors="replace" degrade proprement (caractere
    # illisible affiche comme "?") plutot que de faire echouer tout le
    # rapport pour une seule ligne.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Fenetre glissante en jours (defaut : 7).")
    parser.add_argument("--limit", type=int, default=20, help="Nombre max de lignes par section (defaut : 20).")
    args = parser.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    session = SessionLocal()
    try:
        not_found = _not_found_questions(session, since, limit=args.limit)
        not_useful = _not_useful_ratings_with_score(session, since, limit=args.limit)
    finally:
        session.close()

    print(f"=== Rapport de bouclage feedback FAQ ({args.days} derniers jours) ===\n")

    print(f"--- Questions sans réponse FAQ trouvée ({len(not_found)}) ---")
    if not not_found:
        print("(aucune)")
    for question, occurrences in not_found:
        print(f"  {occurrences:>3}x  {question}")

    print(f"\n--- Réponses notées « pas utile » ({len(not_useful)}) ---")
    if not not_useful:
        print("(aucune)")
    for question, answer, score in not_useful:
        score_label = f"score={float(score):.3f}" if score is not None else "score=introuvable"
        excerpt = answer if len(answer) <= 80 else answer[:77] + "..."
        print(f"  [{score_label}] {question}\n           -> {excerpt}")


if __name__ == "__main__":
    sys.exit(main())
