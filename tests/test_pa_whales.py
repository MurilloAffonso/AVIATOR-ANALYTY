"""Testes de detecção de whales."""

from __future__ import annotations

from app.player_analytics.whales import detect_whales, whale_presence_trend


def test_no_whales_when_population_too_small(make_snapshot):
    snap = make_snapshot(crash=2.0, cashouts=[1.5, 1.5], stakes=[100.0, 1.0])
    result = detect_whales(snap)
    assert result.whale_count == 0
    assert result.mega_whale_count == 0


def test_no_whales_when_distribution_uniform(make_snapshot):
    """Stakes todos iguais: não há outliers."""
    stakes = [10.0] * 20
    snap = make_snapshot(
        crash=2.0,
        cashouts=[1.5] * 20,
        stakes=stakes,
    )
    result = detect_whales(snap)
    assert result.whale_count == 0
    assert result.largest_stake == 10.0
    assert result.median_stake == 10.0


def test_whale_detected_above_p95_and_factor(make_snapshot):
    # 19 stakes pequenos + 1 grande (10x a mediana)
    stakes = [10.0] * 19 + [200.0]
    cashouts = [1.5] * 20
    snap = make_snapshot(crash=2.0, cashouts=cashouts, stakes=stakes)
    result = detect_whales(snap)
    assert result.whale_count >= 1
    assert result.largest_stake == 200.0
    assert result.median_stake == 10.0


def test_mega_whale_detected_above_p99(make_snapshot):
    stakes = [10.0] * 99 + [10000.0]
    cashouts = [1.5] * 100
    snap = make_snapshot(crash=2.0, cashouts=cashouts, stakes=stakes)
    result = detect_whales(snap)
    assert result.mega_whale_count >= 1
    assert result.whale_share_of_volume > 0.5  # whales dominam volume


def test_no_stakes_returns_empty(make_snapshot):
    snap = make_snapshot(crash=2.0, cashouts=[1.5, 1.5, 1.5], stakes=None)
    result = detect_whales(snap)
    assert result.whale_count == 0
    assert result.largest_stake == 0.0


def test_whale_share_correct(make_snapshot):
    # 9 stakes de 10 + 1 stake de 1000. Total = 1090. Whale share = 1000/1090 ≈ 0.917.
    stakes = [10.0] * 9 + [1000.0]
    cashouts = [1.5] * 10
    snap = make_snapshot(crash=2.0, cashouts=cashouts, stakes=stakes)
    result = detect_whales(snap)
    assert 0.85 < result.whale_share_of_volume < 0.95


def test_whale_trend_returns_window_size(make_snapshot):
    snaps = [
        make_snapshot(
            round_id=f"r{i}",
            crash=2.0,
            cashouts=[1.5] * 20,
            stakes=[10.0] * 19 + [200.0],
        )
        for i in range(15)
    ]
    trend = whale_presence_trend(snaps, window=10)
    assert len(trend) == 10
    assert all(v >= 1 for v in trend)
