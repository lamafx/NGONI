"""Appels du moteur aux API « support » de user_service et wallet_service.

Meme source de configuration que le Diagnostic Engine (services_registry.yaml
+ variables d'environnement) : adresse de base et secret partage ne sont
declares qu'une fois."""

from __future__ import annotations

from typing import Any, Optional

import httpx

try:
    from app.domains.diagnostic.registry import SERVICES_REGISTRY_PATH, _load_services_from_yaml
except ImportError:  # pragma: no cover - support running as `main`
    from domains.diagnostic.registry import SERVICES_REGISTRY_PATH, _load_services_from_yaml

TIMEOUT_SECONDS = 5.0


class ServiceUnavailable(RuntimeError):
    """Le microservice ne repond pas, ou refuse l'operation."""


def _service(name: str):
    for service in _load_services_from_yaml(SERVICES_REGISTRY_PATH):
        if service.name == name:
            return service
    raise ServiceUnavailable(f"Service '{name}' absent du registre")


def _call(name: str, method: str, path: str, body: Optional[dict] = None) -> Optional[Any]:
    """Reponse JSON, None si la ressource n'existe pas (404)."""
    service = _service(name)
    try:
        response = httpx.request(
            method,
            f"{service.base_url}/support{path}",
            json=body,
            headers={"X-Internal-Secret": service.internal_secret},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ServiceUnavailable(f"{name} service injoignable ({exc.__class__.__name__})") from exc
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:200]
        raise ServiceUnavailable(f"{name} service : {detail or f'HTTP {response.status_code}'}")
    return response.json()


def get_account(user_id: str) -> Optional[dict]:
    return _call("user", "GET", f"/users/{user_id}")


def get_wallet(user_id: str) -> Optional[dict]:
    return _call("wallet", "GET", f"/wallets/{user_id}")


def open_kyc_submission(user_id: str) -> Optional[dict]:
    return _call("user", "POST", f"/users/{user_id}/kyc-submissions", {})


def kyc_decision(user_id: str, decision: str, reason: Optional[str], submission_id: Optional[str]) -> dict:
    result = _call(
        "user",
        "POST",
        f"/users/{user_id}/kyc-decision",
        {"decision": decision, "reason": reason, "submission_id": submission_id},
    )
    if result is None:
        raise ServiceUnavailable("Compte introuvable cote user service")
    return result
