"""Connexion aux interfaces (client, conseiller, administration).

  POST /auth/login   identifiant + mot de passe -> jeton signe + compte
  GET  /auth/me      compte du jeton presente

Comptes de demonstration (crees au demarrage s'ils manquent, AUTH_DEMO_ACCOUNTS=0
pour les desactiver) : un client relie au compte NGONI de demonstration, deux
conseillers et une administratrice -- mot de passe commun DEMO_PASSWORD."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

try:
    from app.database import get_db
except ImportError:  # pragma: no cover - support running as `main`
    from database import get_db

from .security import check_password, claims_from_header, hash_password, issue_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

DEMO_PASSWORD = os.getenv("AUTH_DEMO_PASSWORD", "ngoni2026")
DEMO_ACCOUNTS = [
    # login, nom affiche, role, compte NGONI (client), conseiller
    ("adou", "Adou Eric Baruch Deverin AYEKOE", "client", "a40e0e00-2006-4514-8000-000000000001", None),
    ("awa.kone", "Awa Koné", "conseiller", None, "conseiller-1"),
    ("yao.kouassi", "Yao Kouassi", "conseiller", None, "conseiller-2"),
    ("fatou.diarra", "Fatou Diarra", "admin", None, "superviseur-1"),
]


def ensure_demo_accounts(db: Session) -> None:
    if os.getenv("AUTH_DEMO_ACCOUNTS", "1") == "0":
        return
    for login, name, role, user_id, agent_id in DEMO_ACCOUNTS:
        exists = db.execute(text("SELECT 1 FROM ia.app_accounts WHERE login = :l"), {"l": login}).first()
        if exists:
            continue
        db.execute(
            text("INSERT INTO ia.app_accounts (login, display_name, role, password_hash, user_id, agent_id) "
                 "VALUES (:l, :n, :r, :h, :u, :a)"),
            {"l": login, "n": name, "r": role, "h": hash_password(DEMO_PASSWORD), "u": user_id, "a": agent_id},
        )
        logger.info("[AUTH] compte de demonstration cree : %s (%s)", login, role)
    db.commit()


def _public(row) -> dict:
    return {
        "login": row["login"],
        "display_name": row["display_name"],
        "role": row["role"],
        "user_id": row["user_id"],
        "agent_id": row["agent_id"],
    }


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT login, display_name, role, password_hash, user_id, agent_id, active "
             "FROM ia.app_accounts WHERE lower(login) = lower(:l)"),
        {"l": payload.login.strip()},
    ).mappings().first()
    # Meme reponse pour un identifiant inconnu et un mauvais mot de passe :
    # ne pas confirmer qu'un compte existe.
    if row is None or not row["active"] or not check_password(payload.password, row["password_hash"]):
        logger.info("[AUTH] connexion refusee : %s", payload.login)
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect.")
    db.execute(text("UPDATE ia.app_accounts SET last_login_at = :now WHERE login = :l"),
               {"now": datetime.now(timezone.utc), "l": row["login"]})
    db.commit()
    account = _public(row)
    logger.info("[AUTH] connexion : %s (%s)", account["login"], account["role"])
    return {"token": issue_token(account), "account": account}


@router.get("/me")
def me(authorization: Optional[str] = Header(None)):
    claims = claims_from_header(authorization)
    if claims is None:
        raise HTTPException(status_code=401, detail="Session absente ou expirée.")
    return {key: claims.get(key) for key in ("login", "display_name", "role", "user_id", "agent_id")}
