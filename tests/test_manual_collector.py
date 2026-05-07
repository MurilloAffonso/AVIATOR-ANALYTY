"""Testes do coletor manual."""

import pytest

from app.collector.manual import save_manual_multiplier


def test_save_valid_multiplier(in_memory_db):
    result = save_manual_multiplier(2.5)
    assert result.id is not None
    assert result.multiplier == 2.5
    assert result.category == "medio"


def test_reject_below_one(in_memory_db):
    with pytest.raises(ValueError):
        save_manual_multiplier(0.5)


def test_repeated_low_value_persists(in_memory_db):
    """Confirma que valores repetidos podem ser inseridos manualmente
    (regressão preventiva: nada no fluxo manual deveria deduplicar)."""
    a = save_manual_multiplier(1.0)
    b = save_manual_multiplier(1.0)
    c = save_manual_multiplier(1.0)
    assert a.id != b.id != c.id
