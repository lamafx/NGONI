"""Mots de passe et jetons de session -- bibliotheque standard uniquement.

Mot de passe : PBKDF2-SHA256 sale (200 000 iterations), stocke sous la forme
`pbkdf2_sha256$iterations$sel$empreinte`.

Jeton : `<charge utile>.<signature>`, tous deux en base64url ; la charge
utile est le JSON du compte (login, role, nom, user_id, agent_id) et sa date
d'expiration, la signature un HMAC-SHA256 avec AUTH_SECRET. Le moteur n'a
donc rien a stocker pour verifier une session, et un jeton modifie (role
eleve, autre compte) est rejete."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional

logger = logging.getLogger(__name__)

ITERATIONS = 200_000
TOKEN_TTL_SECONDS = 12 * 3600

_DEV_SECRET = "dev-auth-secret-change-me"
AUTH_SECRET = os.getenv("AUTH_SECRET") or os.getenv("ADMIN_INTERNAL_SECRET") or _DEV_SECRET
if AUTH_SECRET == _DEV_SECRET:
    logger.warning("[AUTH] AUTH_SECRET non configure : secret de developpement utilise pour signer les jetons.")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    return _b64(hmac.new(AUTH_SECRET.encode(), body.encode(), hashlib.sha256).digest())


def issue_token(claims: dict) -> str:
    body = _b64(json.dumps({**claims, "exp": int(time.time()) + TOKEN_TTL_SECONDS}).encode())
    return f"{body}.{_sign(body)}"


def read_token(token: str) -> Optional[dict]:
    """Claims du jeton, ou None s'il est mal forme, falsifie ou expire."""
    try:
        body, signature = token.split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(body)):
        return None
    try:
        claims = json.loads(_unb64(body))
    except ValueError:
        return None
    if claims.get("exp", 0) < time.time():
        return None
    return claims


def claims_from_header(authorization: Optional[str]) -> Optional[dict]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return read_token(authorization[7:].strip())
