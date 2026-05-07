from __future__ import annotations

from app.analyzer import categorize_multiplier
from app.database import SessionLocal
from app.models import RoundResult


def save_manual_multiplier(multiplier: float) -> RoundResult:
    category = categorize_multiplier(multiplier)
    with SessionLocal() as session:
        result = RoundResult(multiplier=multiplier, category=category)
        session.add(result)
        session.commit()
        session.refresh(result)
        return result
