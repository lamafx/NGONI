"""Compte de demonstration -- un VRAI compte NGONI, cree dans la base, pour
rejouer a l'identique le parcours « verification d'identite » devant un jury.

    python scripts/compte_demo.py creer          # cree le compte (s'il n'existe pas)
    python scripts/compte_demo.py reinitialiser  # remet le compte dans son etat de depart
    python scripts/compte_demo.py afficher       # etat actuel du compte
    python scripts/compte_demo.py supprimer      # supprime le compte et tout son historique

Sous Docker :  docker compose exec fastapi python scripts/compte_demo.py <commande>

Options de `creer` : --nouveau (identifiant aleatoire, pour un second compte),
--nom, --prenoms, --naissance JJ/MM/AAAA, --ville.

Etat de depart : identite de la CNI de demonstration (AYEKOE Adou Eric Baruch
Deverin, ne le 14/05/2006, Cote d'Ivoire), verification d'identite REFUSEE il y
a 3 jours (photo floue), portefeuille avec quelques operations. Le parcours
attendu -- refus constate par l'assistant, nouvelle piece, validation par un
conseiller, statut a jour -- est decrit dans DEMO-JURY.md.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

DEMO_USER_ID = "a40e0e00-2006-4514-8000-000000000001"

DEFAULTS = {
    "nom": "AYEKOE",
    "prenoms": "Adou Eric Baruch Deverin",
    "naissance": "14/05/2006",
    "ville": "Abidjan",
    "pays_id": 1,  # users.countries : Cote d'Ivoire
}


def _engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL absente : lancer ce script dans le conteneur fastapi (voir l'en-tete).")
    return create_engine(url)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _exists(conn, user_id):
    return conn.execute(text("SELECT 1 FROM users.users WHERE id = :id"), {"id": user_id}).first() is not None


def creer(conn, user_id, nom, prenoms, naissance, ville):
    if _exists(conn, user_id):
        print(f"Le compte {user_id} existe deja : utiliser `reinitialiser`.")
        return False
    now = _now()
    day, month, year = (int(x) for x in naissance.split("/"))
    username = f"{prenoms.split()[0].lower()}.{nom.lower()}"[:30]
    if user_id != DEMO_USER_ID:
        username = f"{username}.{user_id[:4]}"
    conn.execute(
        text(
            """
            INSERT INTO users.users (id, username, display_name, phone_number, city, country_id,
                date_of_birth, status, kyc_status, kyc_level, followers_count, following_count,
                videos_count, phone_verified_at, last_active_at, created_at, updated_at)
            VALUES (:id, :username, :display_name, :phone, :ville, :pays, :naissance, 'ACTIVE',
                'REJECTED', 'none', 1240, 180, 37, :created, :active, :created, :now)
            """
        ),
        {
            "id": user_id, "username": username, "display_name": f"{prenoms} {nom}",
            "phone": "+2250700000001" if user_id == DEMO_USER_ID else f"+22507{uuid.UUID(user_id).int % 10**8:08d}", "ville": ville, "pays": DEFAULTS["pays_id"],
            "naissance": date(year, month, day), "created": now - timedelta(days=200),
            "active": now - timedelta(hours=1), "now": now,
        },
    )
    rejected_at = now - timedelta(days=3)
    conn.execute(
        text(
            "INSERT INTO users.kyc_submissions (id, user_id, level, status, rejection_reason, "
            "reviewed_at, created_at, updated_at) VALUES (:sid, :uid, 'level_1', 'rejected', :reason, "
            ":reviewed, :created, :reviewed)"
        ),
        {
            "sid": uuid.uuid4(), "uid": user_id,
            "reason": "Photo floue : les mentions de la pièce sont illisibles",
            "created": rejected_at - timedelta(hours=5), "reviewed": rejected_at,
        },
    )
    _creer_portefeuille(conn, user_id, now)
    return True


def _creer_portefeuille(conn, user_id, now):
    """Portefeuille et operations. Facultatif : sans droit d'ecriture sur le
    schema `wallet`, le compte est cree sans portefeuille."""
    wallet_id = uuid.uuid4()
    operations = [
        ("GIFT_RECEIVED", "SUCCESS", 15000, 15000, now - timedelta(days=12)),
        ("GIFT_RECEIVED", "SUCCESS", 22500, 37500, now - timedelta(days=6)),
        ("WITHDRAWAL", "FAILED", 20000, 37500, now - timedelta(days=4)),
        ("GIFT_RECEIVED", "SUCCESS", 7500, 45000, now - timedelta(days=1)),
    ]
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO wallet.wallets (id, user_id, balance, currency, status, kyc_verified, "
                    "total_earned, created_at, updated_at) VALUES (:wid, :uid, 45000, 'XOF', 'ACTIVE', "
                    "false, 45000, :created, :now)"
                ),
                {"wid": wallet_id, "uid": user_id, "created": now - timedelta(days=200), "now": now},
            )
            for index, (kind, status, amount, balance, at) in enumerate(operations, start=1):
                reference = f"{'WDR' if kind == 'WITHDRAWAL' else 'GFT'}-DEMO{index:04d}"
                conn.execute(
                    text(
                        "INSERT INTO wallet.wallet_transactions (id, user_id, wallet_id, type, status, "
                        "amount, net_amount, balance_after, currency, idempotency_key, reference_id, "
                        "created_at) VALUES (:id, :uid, :wid, :type, :status, :amount, :amount, "
                        ":balance, 'XOF', :key, :ref, :at)"
                    ),
                    {"id": uuid.uuid4(), "uid": user_id, "wid": wallet_id, "type": kind, "status": status,
                     "amount": amount, "balance": balance, "key": f"demo-{user_id}-{index}",
                     "ref": reference, "at": at},
                )
    except ProgrammingError:
        print("  ! portefeuille non cree : droits d'ecriture absents sur le schema `wallet`.")


def _purger_historique(conn, user_id):
    """Donnees du moteur liees au compte : pieces, journal, conversations,
    reclamations, diagnostics."""
    conversations = [
        row[0] for row in conn.execute(
            text("SELECT conversation_id FROM ia.conversations WHERE user_id = :uid"), {"uid": user_id}
        )
    ]
    owners = [user_id, *conversations]
    conn.execute(text("DELETE FROM ia.identity_documents WHERE user_id = :uid"), {"uid": user_id})
    conn.execute(text("DELETE FROM ia.agent_actions WHERE user_id = :uid"), {"uid": user_id})
    conn.execute(text("DELETE FROM ia.diagnostic_audit_log WHERE user_id = :uid"), {"uid": user_id})
    conn.execute(text("DELETE FROM ia.diagnostic_sessions WHERE user_id = :uid"), {"uid": user_id})
    conn.execute(text("DELETE FROM ia.complaints WHERE user_id = ANY(:owners)"), {"owners": owners})
    if conversations:
        conn.execute(
            text("DELETE FROM ia.conversation_messages WHERE conversation_id = ANY(:ids)"),
            {"ids": conversations},
        )
        conn.execute(text("DELETE FROM ia.conversations WHERE conversation_id = ANY(:ids)"), {"ids": conversations})
    return len(conversations)


def supprimer(conn, user_id):
    purged = _purger_historique(conn, user_id)
    conn.execute(text("DELETE FROM wallet.wallet_transactions WHERE user_id = :uid"), {"uid": user_id})
    conn.execute(text("DELETE FROM wallet.wallets WHERE user_id = :uid"), {"uid": user_id})
    conn.execute(text("DELETE FROM users.kyc_submissions WHERE user_id = :uid"), {"uid": user_id})
    conn.execute(text("DELETE FROM users.users WHERE id = :uid"), {"uid": user_id})
    return purged


def afficher(conn, user_id):
    user = conn.execute(
        text("SELECT username, display_name, status, kyc_status, kyc_level, date_of_birth "
             "FROM users.users WHERE id = :id"),
        {"id": user_id},
    ).first()
    if user is None:
        print(f"Aucun compte {user_id}.")
        return
    print(f"Compte      {user_id}")
    print(f"Identite    {user.display_name} (@{user.username}), ne(e) le {user.date_of_birth:%d/%m/%Y}")
    print(f"Statut      {user.status} · KYC {user.kyc_status} (niveau {user.kyc_level})")
    for sub in conn.execute(
        text("SELECT status, rejection_reason, created_at FROM users.kyc_submissions "
             "WHERE user_id = :id ORDER BY created_at"),
        {"id": user_id},
    ):
        print(f"  KYC       {sub.created_at:%d/%m %H:%M}  {sub.status}  {sub.rejection_reason or ''}")
    wallet = conn.execute(text("SELECT balance, currency FROM wallet.wallets WHERE user_id = :id"),
                          {"id": user_id}).first()
    print(f"Solde       {wallet.balance:.0f} {wallet.currency}" if wallet else "Solde       (pas de portefeuille)")
    counts = conn.execute(
        text("SELECT (SELECT count(*) FROM ia.conversations WHERE user_id = :id), "
             "(SELECT count(*) FROM ia.identity_documents WHERE user_id = :id), "
             "(SELECT count(*) FROM ia.agent_actions WHERE user_id = :id)"),
        {"id": user_id},
    ).first()
    print(f"Moteur      {counts[0]} conversation(s) · {counts[1]} piece(s) · {counts[2]} action(s) de conseiller")
    print(f"Chat        http://localhost:5173/?compte={user_id}#/chat")


def main():
    parser = argparse.ArgumentParser(description="Compte de demonstration NGONI.")
    parser.add_argument("commande", choices=["creer", "reinitialiser", "afficher", "supprimer"])
    parser.add_argument("--id", default=None, help=f"identifiant du compte (defaut : {DEMO_USER_ID})")
    parser.add_argument("--nouveau", action="store_true", help="creer un compte avec un identifiant aleatoire")
    parser.add_argument("--nom", default=DEFAULTS["nom"])
    parser.add_argument("--prenoms", default=DEFAULTS["prenoms"])
    parser.add_argument("--naissance", default=DEFAULTS["naissance"], help="JJ/MM/AAAA")
    parser.add_argument("--ville", default=DEFAULTS["ville"])
    args = parser.parse_args()

    user_id = str(uuid.uuid4()) if args.nouveau else (args.id or DEMO_USER_ID)
    with _engine().begin() as conn:
        if args.commande == "creer":
            if creer(conn, user_id, args.nom.upper(), args.prenoms, args.naissance, args.ville):
                print("Compte cree.")
        elif args.commande == "supprimer":
            purged = supprimer(conn, user_id)
            print(f"Compte supprime ({purged} conversation(s) effacee(s)).")
            return
        elif args.commande == "reinitialiser":
            try:
                with conn.begin_nested():
                    supprimer(conn, user_id)
                    creer(conn, user_id, args.nom.upper(), args.prenoms, args.naissance, args.ville)
                print("Compte remis dans son etat de depart.")
            except ProgrammingError:
                sys.exit(
                    "Reinitialisation impossible : droits de suppression absents sur les schemas "
                    "`users` / `wallet` (voir DEMO-JURY.md). Creer plutot un nouveau compte : "
                    "python scripts/compte_demo.py creer --nouveau"
                )
        afficher(conn, user_id)


if __name__ == "__main__":
    main()
