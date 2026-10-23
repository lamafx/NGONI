"""Verification du secret partage entre le Diagnostic Engine et ce service.

Meme convention que le vrai wallet-service : header `X-Internal-Secret`,
compare a WALLET_SERVICE_INTERNAL_SECRET (voir aussi registry.py cote Engine,
qui envoie ce header via WALLET_SERVICE_INTERNAL_SECRET)."""

import os

from fastapi import Header, HTTPException

INTERNAL_SECRET = os.getenv("WALLET_SERVICE_INTERNAL_SECRET", "test-secret")


def require_internal_secret(x_internal_secret: str = Header(...)) -> None:
    if x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
