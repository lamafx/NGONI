"""Client HTTP partage vers Rasa (webhook + parse), avec retry -- utilise par
app/main.py (webhook Core, raccourci ask_faq) et app/domains/nlu/engines.py
(moteur "rasa" du selecteur de modele). Un seul endroit pour cette logique,
au lieu de la dupliquer entre les deux appelants.
"""

from __future__ import annotations

import asyncio
import logging
from os import getenv

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

RASA_WEBHOOK_URL = getenv("RASA_WEBHOOK_URL", "http://127.0.0.1:5005/webhooks/rest/webhook")
RASA_PARSE_URL = getenv("RASA_PARSE_URL", "http://127.0.0.1:5005/model/parse")
RASA_RETRY_COUNT = int(getenv("RASA_RETRY_COUNT", "3"))
RASA_RETRY_DELAY = float(getenv("RASA_RETRY_DELAY", "1.0"))


async def call_rasa_with_retry(url: str, json_body: dict, headers: dict | None = None) -> httpx.Response:
    last_error = None
    for attempt in range(1, RASA_RETRY_COUNT + 1):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=json_body, headers=headers, timeout=10.0)
                response.raise_for_status()
                return response
        except httpx.RequestError as exc:
            last_error = exc
            logger.warning("Rasa request failed (attempt %s/%s) to %s: %s", attempt, RASA_RETRY_COUNT, url, exc)
            if attempt < RASA_RETRY_COUNT:
                await asyncio.sleep(RASA_RETRY_DELAY)
        except httpx.HTTPStatusError as exc:
            logger.warning("Rasa HTTP error (attempt %s/%s) to %s: %s", attempt, RASA_RETRY_COUNT, url, exc)
            raise

    raise HTTPException(status_code=502, detail=f"Impossible de contacter Rasa après {RASA_RETRY_COUNT} tentatives: {last_error}")
