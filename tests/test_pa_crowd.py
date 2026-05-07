"""Testes de greed index, panic exit, crowd aggression."""

from __future__ import annotations

from app.player_analytics.crowd_behavior import (
    compute_crowd_metrics,
    crowd_aggression,
    early_exit_rate,
    greed_index,
    late_exit_rate,
    panic_exit_score,
)


# ---------- greed index ----------

def test_greed_zero_when_no_cashouts(make_snapshot):
    snap = make_snapshot(crash=2.0, cashouts=[], alive=10)
    assert greed_index(snap) == 0.0


def test_greed_low_for_early_cashouts(make_snapshot):
    snap = make_snapshot(crash=10.0, cashouts=[1.05, 1.10, 1.15])
    assert greed_index(snap) < 25  # mediana ~1.10


def test_greed_high_for_late_cashouts(make_snapshot):
    snap = make_snapshot(crash=20.0, cashouts=[8.0, 10.0, 12.0])
    assert greed_index(snap) >= 90


def test_greed_mid_at_2x(make_snapshot):
    snap = make_snapshot(crash=5.0, cashouts=[2.0, 2.0, 2.0])
    assert 45 <= greed_index(snap) <= 55  # ancora em 50


# ---------- panic exit ----------

def test_panic_zero_below_min_population(make_snapshot):
    snap = make_snapshot(crash=2.0, cashouts=[1.1, 1.1])  # n=2 < 5
    assert panic_exit_score(snap) == 0.0


def test_panic_high_when_mass_exit_at_low_multiplier(make_snapshot):
    # 10 cashouts em janela apertada perto de 1.10x
    cashouts = [1.10, 1.11, 1.12, 1.10, 1.11, 1.13, 1.10, 1.12, 1.11, 1.10]
    snap = make_snapshot(crash=2.0, cashouts=cashouts)
    score = panic_exit_score(snap)
    assert score > 50


def test_panic_low_when_cashouts_spread_out(make_snapshot):
    cashouts = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    snap = make_snapshot(crash=10.0, cashouts=cashouts)
    assert panic_exit_score(snap) < 20


def test_panic_low_when_concentrated_but_high_multiplier(make_snapshot):
    """Concentração em 5x não é pânico — é euforia coletiva."""
    cashouts = [5.00, 5.05, 5.05, 5.10, 5.05, 5.00, 5.10, 5.00, 5.05, 5.05]
    snap = make_snapshot(crash=8.0, cashouts=cashouts)
    assert panic_exit_score(snap) < 20


# ---------- crowd aggression ----------

def test_aggression_zero_for_empty_round(make_snapshot):
    snap = make_snapshot(player_count=0, cashouts=[], alive=0)
    assert crowd_aggression(snap) == 0.0


def test_aggression_combines_greed_and_participation(make_snapshot):
    # Muitos jogadores + cashouts altos = alta agressão
    cashouts = [3.0] * 100
    snap = make_snapshot(crash=8.0, cashouts=cashouts, player_count=120)
    score = crowd_aggression(snap)
    assert score >= 70


# ---------- exit rates ----------

def test_early_exit_rate_counts_below_threshold(make_snapshot):
    snap = make_snapshot(crash=3.0, cashouts=[1.10, 1.20, 1.40, 1.60, 2.50])
    assert early_exit_rate(snap, threshold=1.5) == 3 / 5


def test_late_exit_rate_counts_above_threshold(make_snapshot):
    snap = make_snapshot(crash=10.0, cashouts=[1.5, 2.0, 5.0, 6.0, 7.5])
    assert late_exit_rate(snap, threshold=5.0) == 3 / 5


def test_exit_rates_zero_when_no_cashouts(make_snapshot):
    snap = make_snapshot(crash=2.0, cashouts=[], alive=5)
    assert early_exit_rate(snap) == 0.0
    assert late_exit_rate(snap) == 0.0


# ---------- bundle ----------

def test_compute_crowd_metrics_returns_all_fields(sample_snapshot):
    m = compute_crowd_metrics(sample_snapshot)
    assert 0 <= m.greed_index <= 100
    assert 0 <= m.panic_exit_score <= 100
    assert 0 <= m.crowd_aggression <= 100
    assert 0 <= m.early_exit_rate <= 1
    assert 0 <= m.late_exit_rate <= 1
