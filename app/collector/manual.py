"""Inserção manual de multiplicadores."""

from __future__ import annotations

from app.analyzer import categorize_multiplier
from app.database import SessionLocal
from app.models import RoundResult


def save_manual_multiplier(multiplier: float) -> RoundResult:
    """Salva um multiplicador inserido manualmente.

    Raises:
        ValueError: se ``multiplier`` for menor que 1.0 (valor inválido para
        Aviator, onde todo multiplicador é >= 1.00x).
    """
    if multiplier < 1.0:
        raise ValueError(
            f"Multiplicador inválido: {multiplier}. Deve ser >= 1.0."
        )

    category = categorize_multiplier(multiplier)
    with SessionLocal() as session:
        result = RoundResult(multiplier=multiplier, category=category)
        session.add(result)
        session.commit()
        session.refresh(result)
        return result
