"""Formatage commun des dates dans les messages utilisateur du diagnostic
user -- meme convention que wallet_stub/diagnostic/formatting.py."""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def format_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.strftime("%d/%m/%Y à %H:%M")
