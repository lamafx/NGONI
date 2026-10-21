"""Parsing de texte libre (date/montant) pour la recherche de repli d'un
retrait par date+montant quand l'utilisateur n'a pas sa reference de
transaction (voir withdrawal.py::_resolve_by_date_amount). Perimetre
volontairement borne : les expressions non reconnues retournent None plutot
qu'une approximation risquee -- dans ce cas l'appelant traite le champ comme
non fourni."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_AMOUNT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)")


def parse_amount(text: str | None) -> float | None:
    if not text:
        return None
    match = _AMOUNT_PATTERN.search(text.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


_FRENCH_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

_WEEKDAYS_FR = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6,
}

_EXPLICIT_DATE_PATTERN = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")
_FRENCH_MONTH_DATE_PATTERN = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(_FRENCH_MONTHS) + r")\b(?:\s+(\d{4}))?"
)


def parse_relative_date_fr(text: str | None, reference: datetime) -> date | None:
    if not text:
        return None
    lowered = text.strip().lower()
    today = reference.date()

    if "avant-hier" in lowered or "avant hier" in lowered:
        return today - timedelta(days=2)
    if "hier" in lowered:
        return today - timedelta(days=1)
    if "aujourd'hui" in lowered or "aujourdhui" in lowered or any(
        marker in lowered for marker in ("ce matin", "cet après-midi", "cet apres-midi", "ce soir")
    ):
        return today

    match = _EXPLICIT_DATE_PATTERN.search(lowered)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None

    match = _FRENCH_MONTH_DATE_PATTERN.search(lowered)
    if match:
        day = int(match.group(1))
        month = _FRENCH_MONTHS[match.group(2)]
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        # Sans annee explicite, un incident deja survenu ne peut pas etre
        # dans le futur -- rembobine d'un an plutot que de retourner une
        # date invalide pour ce cas d'usage.
        if match.group(3) is None and candidate > today:
            candidate = date(year - 1, month, day)
        return candidate

    for name, weekday in _WEEKDAYS_FR.items():
        if name in lowered:
            delta = (today.weekday() - weekday) % 7
            # "mardi dernier" dit un mardi designe le mardi PRECEDENT (7
            # jours avant), jamais le jour meme.
            delta = delta or 7
            return today - timedelta(days=delta)

    return None
