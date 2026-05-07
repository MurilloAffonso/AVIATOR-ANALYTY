from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class SummaryStats:
    total_rounds: int
    avg_multiplier: float
    max_multiplier: float
    pct_below_1_5: float
    pct_above_3: float
    pct_above_10: float


@dataclass
class AdvancedAnalysis:
    consecutive_lows_current: int
    consecutive_lows_max: int
    avg_interval_above_10: float
    avg_interval_above_50: float
    volatility_20: float
    volatility_50: float
    volatility_100: float
    low_concentration_alert: bool
    variance_spike_alert: bool
    risk_score: int
    opportunity_score: int


def categorize_multiplier(multiplier: float) -> str:
    if multiplier < 1.5:
        return "baixo"
    if multiplier < 3:
        return "medio"
    if multiplier < 10:
        return "alto"
    if multiplier < 50:
        return "grande"
    return "explosivo"


def summarize(df: pd.DataFrame) -> SummaryStats:
    if df.empty:
        return SummaryStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)

    total = len(df)
    multipliers = df["multiplier"]

    return SummaryStats(
        total_rounds=total,
        avg_multiplier=float(multipliers.mean()),
        max_multiplier=float(multipliers.max()),
        pct_below_1_5=float((multipliers < 1.5).mean() * 100),
        pct_above_3=float((multipliers >= 3).mean() * 100),
        pct_above_10=float((multipliers >= 10).mean() * 100),
    )


def _consecutive_lows_stats(multipliers: pd.Series, threshold: float = 1.5) -> tuple[int, int]:
    current = 0
    max_streak = 0
    for value in multipliers:
        if value < threshold:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0

    trailing = 0
    for value in reversed(multipliers.tolist()):
        if value < threshold:
            trailing += 1
        else:
            break

    return trailing, max_streak


def _avg_interval_for_threshold(multipliers: pd.Series, threshold: float) -> float:
    idx = multipliers[multipliers >= threshold].index.tolist()
    if len(idx) < 2:
        return 0.0
    intervals = [idx[i] - idx[i - 1] for i in range(1, len(idx))]
    return float(sum(intervals) / len(intervals))


def _volatility(multipliers: pd.Series, window: int) -> float:
    if len(multipliers) < 2:
        return 0.0
    subset = multipliers.tail(window)
    return float(subset.std(ddof=0)) if not subset.empty else 0.0


def analyze_advanced(df: pd.DataFrame) -> AdvancedAnalysis:
    if df.empty:
        return AdvancedAnalysis(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, False, False, 0, 0)

    multipliers = df["multiplier"].reset_index(drop=True)
    trailing_lows, max_lows = _consecutive_lows_stats(multipliers)
    interval_10 = _avg_interval_for_threshold(multipliers, 10.0)
    interval_50 = _avg_interval_for_threshold(multipliers, 50.0)

    vol20 = _volatility(multipliers, 20)
    vol50 = _volatility(multipliers, 50)
    vol100 = _volatility(multipliers, 100)

    short_window = multipliers.tail(30) if len(multipliers) >= 30 else multipliers
    baseline_window = multipliers.tail(120) if len(multipliers) >= 120 else multipliers

    low_ratio_recent = float((short_window < 1.5).mean()) if len(short_window) else 0.0
    low_ratio_baseline = float((baseline_window < 1.5).mean()) if len(baseline_window) else 0.0
    low_concentration_alert = low_ratio_recent > max(0.65, low_ratio_baseline + 0.20)

    recent_var = float(short_window.var(ddof=0)) if len(short_window) > 1 else 0.0
    baseline_var = float(baseline_window.var(ddof=0)) if len(baseline_window) > 1 else 0.0
    variance_spike_alert = baseline_var > 0 and recent_var > baseline_var * 1.8

    risk_raw = (
        min(40, trailing_lows * 6)
        + min(25, int(low_ratio_recent * 35))
        + (20 if variance_spike_alert else 0)
        + min(15, int(vol20 * 2.5))
    )
    risk_score = max(0, min(100, int(risk_raw)))

    opportunity_raw = (
        min(30, trailing_lows * 4)
        + min(25, int(interval_10 / 2))
        + min(25, int(interval_50 / 3))
        + (20 if low_concentration_alert else 0)
    )
    opportunity_score = max(0, min(100, int(opportunity_raw)))

    return AdvancedAnalysis(
        consecutive_lows_current=trailing_lows,
        consecutive_lows_max=max_lows,
        avg_interval_above_10=interval_10,
        avg_interval_above_50=interval_50,
        volatility_20=vol20,
        volatility_50=vol50,
        volatility_100=vol100,
        low_concentration_alert=low_concentration_alert,
        variance_spike_alert=variance_spike_alert,
        risk_score=risk_score,
        opportunity_score=opportunity_score,
    )
