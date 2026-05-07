"""Testes do módulo de análise estatística."""

import pandas as pd
import pytest

from app.analyzer import (
    AdvancedAnalysis,
    SummaryStats,
    analyze_advanced,
    categorize_multiplier,
    summarize,
)


# ---------- categorize_multiplier ----------

@pytest.mark.parametrize(
    "value,expected",
    [
        (1.0, "baixo"),
        (1.49, "baixo"),
        (1.5, "medio"),
        (2.99, "medio"),
        (3.0, "alto"),
        (9.99, "alto"),
        (10.0, "grande"),
        (49.99, "grande"),
        (50.0, "explosivo"),
        (1000.0, "explosivo"),
    ],
)
def test_categorize_boundaries(value, expected):
    assert categorize_multiplier(value) == expected


# ---------- summarize ----------

def test_summarize_empty():
    df = pd.DataFrame(columns=["multiplier"])
    stats = summarize(df)
    assert stats == SummaryStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_summarize_basic():
    df = pd.DataFrame({"multiplier": [1.0, 1.2, 2.5, 5.0, 15.0]})
    stats = summarize(df)
    assert stats.total_rounds == 5
    assert stats.max_multiplier == 15.0
    assert stats.pct_below_1_5 == 40.0   # 1.0 e 1.2
    assert stats.pct_above_3 == 40.0     # 5.0 e 15.0
    assert stats.pct_above_10 == 20.0    # somente 15.0


# ---------- analyze_advanced ----------

def test_analyze_advanced_empty():
    df = pd.DataFrame(columns=["multiplier"])
    result = analyze_advanced(df)
    assert isinstance(result, AdvancedAnalysis)
    assert result.consecutive_lows_current == 0
    assert result.risk_score == 0
    assert result.opportunity_score == 0


def test_consecutive_lows_at_tail():
    df = pd.DataFrame({"multiplier": [5.0, 1.0, 1.2, 1.1, 1.0, 1.3]})
    result = analyze_advanced(df)
    assert result.consecutive_lows_current == 5
    assert result.consecutive_lows_max == 5


def test_consecutive_lows_streak_broken_at_end():
    df = pd.DataFrame({"multiplier": [1.0, 1.0, 1.0, 5.0, 2.5]})
    result = analyze_advanced(df)
    assert result.consecutive_lows_current == 0
    assert result.consecutive_lows_max == 3


def test_avg_interval_above_10():
    # Highs em índices 0, 3, 7 -> intervalos 3 e 4 -> média 3.5
    df = pd.DataFrame({
        "multiplier": [12.0, 1.1, 1.2, 15.0, 1.0, 2.0, 1.5, 11.0]
    })
    result = analyze_advanced(df)
    assert result.avg_interval_above_10 == 3.5


def test_scores_clamped_to_valid_range():
    # Patológico: longa sequência de baixos.
    df = pd.DataFrame({"multiplier": [1.0] * 200})
    result = analyze_advanced(df)
    assert 0 <= result.risk_score <= 100
    assert 0 <= result.opportunity_score <= 100


def test_volatility_zero_when_constant():
    df = pd.DataFrame({"multiplier": [2.0] * 50})
    result = analyze_advanced(df)
    assert result.volatility_20 == 0.0
    assert result.volatility_50 == 0.0
