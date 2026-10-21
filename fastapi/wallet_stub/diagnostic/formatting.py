"""Formatage commun des dates/durees dans les messages utilisateur du
diagnostic wallet -- evite de repeter le meme format (%d/%m/%Y a %H:%M, deja
duplique 3 fois entre service.py/service_topup.py/service_gift.py) et la meme
logique minutes -> texte lisible dans chaque service_*.py.

Utilise pour rendre les reponses du bot explicites sur la date/l'heure et la
duree d'attente quand elles sont disponibles, plutot que des formulations
vagues ("depuis un delai anormalement long") qui ne disent pas depuis quand
precisement."""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def format_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.strftime("%d/%m/%Y à %H:%M")


def format_duration_minutes(age_minutes: float) -> str:
    total_minutes = round(age_minutes)
    if total_minutes < 60:
        return f"{total_minutes} minute{'s' if total_minutes != 1 else ''}"
    hours, minutes = divmod(total_minutes, 60)
    text = f"{hours} heure{'s' if hours != 1 else ''}"
    if minutes:
        text += f" et {minutes} minute{'s' if minutes != 1 else ''}"
    return text
