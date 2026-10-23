"""Confrontation automatique entre la piece d'identite lue par l'OCR et le
compte NGONI. Elle PREPARE la decision du conseiller, elle ne la prend
jamais : chaque ligne dit ce que la piece indique, ce que le compte indique,
et si les deux concordent."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Dict, List, Optional

# Nationalite lue sur la piece -> pays du compte (noms normalises).
_NATIONALITY_COUNTRY = {
    "IVOIRIENNE": "COTE D IVOIRE", "IVOIRIEN": "COTE D IVOIRE", "CIV": "COTE D IVOIRE",
    "SENEGALAISE": "SENEGAL", "SENEGALAIS": "SENEGAL", "SEN": "SENEGAL",
    "MALIENNE": "MALI", "MALIEN": "MALI", "MLI": "MALI",
    "BURKINABE": "BURKINA FASO", "BFA": "BURKINA FASO",
    "TOGOLAISE": "TOGO", "TOGOLAIS": "TOGO", "TGO": "TOGO",
    "FRANCAISE": "FRANCE", "FRANCAIS": "FRANCE", "FRA": "FRANCE",
}


def _norm(text: Optional[str]) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", text)).strip()


def _row(label: str, document: Optional[str], account: Optional[str], verdict: str) -> Dict[str, Optional[str]]:
    # verdict : "ok" (concordant) | "ko" (different) | "na" (non verifiable)
    return {"label": label, "document": document or "—", "account": account or "—", "verdict": verdict}


def compare(fields: List[dict], account: Optional[dict]) -> List[Dict[str, Optional[str]]]:
    if not fields:
        return []
    values = {field["key"]: field["value"] for field in fields}
    account = account or {}
    rows = []

    # Nom et prenoms : chaque mot du nom affiche du compte doit figurer sur la
    # piece, et le nom de famille de la piece dans le compte.
    document_name = " ".join(v for v in (values.get("surname"), values.get("given_names")) if v)
    account_name = account.get("display_name")
    if document_name and account_name:
        doc_tokens = set(_norm(document_name).split())
        acc_tokens = set(_norm(account_name).split())
        surname_ok = set(_norm(values.get("surname")).split()) <= acc_tokens
        verdict = "ok" if acc_tokens <= doc_tokens and surname_ok else "ko"
        rows.append(_row("Nom et prénoms", document_name, account_name, verdict))
    else:
        rows.append(_row("Nom et prénoms", document_name, account_name, "na"))

    birth = values.get("birth_date")
    account_birth = account.get("date_of_birth")
    if birth and account_birth:
        day, month, year = birth.split("/")
        verdict = "ok" if f"{year}-{month}-{day}" == account_birth else "ko"
        shown = "/".join(reversed(account_birth.split("-")))
        rows.append(_row("Date de naissance", birth, shown, verdict))
    else:
        rows.append(_row("Date de naissance", birth, None, "na"))

    nationality = values.get("nationality")
    country = account.get("country")
    if nationality and country:
        expected = _NATIONALITY_COUNTRY.get(_norm(nationality))
        verdict = "na" if expected is None else ("ok" if expected == _norm(country) else "ko")
        rows.append(_row("Nationalité / pays du compte", nationality, country, verdict))

    expiry = values.get("expiry_date")
    if expiry:
        try:
            day, month, year = (int(part) for part in expiry.split("/"))
            valid = date(year, month, day) >= date.today()
            rows.append(_row("Validité de la pièce", f"jusqu'au {expiry}", None, "ok" if valid else "ko"))
        except ValueError:
            pass
    return rows
