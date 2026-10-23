"""Authentification des interfaces (app/domains/auth, app/shared/admin_auth) :
mots de passe, jetons signes, et regles d'acces par role -- sans base."""

import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.auth import security  # noqa: E402
from app.shared import admin_auth  # noqa: E402


def _bearer(role, **extra):
    return "Bearer " + security.issue_token({"login": "x", "role": role, **extra})


def test_password_hash_is_salted_and_verifiable():
    first = security.hash_password("ngoni2026")
    second = security.hash_password("ngoni2026")
    assert first != second
    assert first.startswith("pbkdf2_sha256$")
    assert security.check_password("ngoni2026", first)
    assert not security.check_password("autre", first)


def test_token_roundtrip_and_tampering():
    token = security.issue_token({"login": "awa.kone", "role": "conseiller"})
    assert security.read_token(token)["role"] == "conseiller"
    body, signature = token.split(".")
    forged_body = security._b64(b'{"login": "awa.kone", "role": "admin", "exp": 9999999999}')
    assert security.read_token(f"{forged_body}.{signature}") is None
    assert security.read_token("pas-un-jeton") is None


def test_expired_token_is_rejected(monkeypatch):
    monkeypatch.setattr(security, "TOKEN_TTL_SECONDS", -1)
    assert security.read_token(security.issue_token({"role": "admin"})) is None


def test_support_routes_accept_agent_and_admin_only():
    assert admin_auth.require_admin_auth(None, _bearer("conseiller"))["role"] == "conseiller"
    assert admin_auth.require_admin_auth(None, _bearer("admin"))["role"] == "admin"
    for header in (_bearer("client", user_id="u"), None, "Bearer faux"):
        with pytest.raises(HTTPException) as error:
            admin_auth.require_admin_auth(None, header)
        assert error.value.status_code == 401


def test_admin_routes_refuse_agents_with_403():
    assert admin_auth.require_admin_role(None, _bearer("admin"))["role"] == "admin"
    with pytest.raises(HTTPException) as error:
        admin_auth.require_admin_role(None, _bearer("conseiller"))
    assert error.value.status_code == 403


def test_client_identity_comes_from_token():
    assert admin_auth.require_client(_bearer("client", user_id="compte-1")) == "compte-1"
    with pytest.raises(HTTPException):
        admin_auth.require_client(_bearer("conseiller"))
    assert admin_auth.optional_client(None) is None
