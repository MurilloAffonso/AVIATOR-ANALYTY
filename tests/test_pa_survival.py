"""Testes da curva de sobrevivência."""

from __future__ import annotations

import math

from app.player_analytics.survival import (
    aggregate_survival_curve,
    survival_curve_for_round,
)


def test_empty_round_returns_empty(make_snapshot):
    snap = make_snapshot(player_count=0, cashouts=[], alive=0)
    assert survival_curve_for_round(snap) == []


def test_starts_at_one_and_decreases(make_snapshot):
    snap = make_snapshot(crash=3.0, cashouts=[1.5, 2.0, 2.5], alive=0)
    curve = survival_curve_for_round(snap)
    survivals = [p.survival for p in curve]
    # Começa em 1.0
    assert math.isclose(survivals[0], 1.0)
    # Cada passo é não-crescente
    for prev, nxt in zip(survivals, survivals[1:]):
        assert nxt <= prev + 1e-9


def test_all_cashout_drops_to_zero(make_snapshot):
    snap = make_snapshot(crash=5.0, cashouts=[1.5, 2.0, 3.0], alive=0)
    curve = survival_curve_for_round(snap)
    assert math.isclose(curve[-1].survival, 0.0)


def test_censored_players_keep_residual_survival(make_snapshot):
    """Se 5 jogadores cashearam e 5 crasharam, S(crash) ≈ 0.5."""
    snap = make_snapshot(
        crash=2.5,
        cashouts=[1.2, 1.3, 1.5, 1.7, 2.0],
        alive=5,
    )
    curve = survival_curve_for_round(snap)
    # Após todos os cashouts, S = 5/10 = 0.5
    pre_crash = [p for p in curve if p.multiplier < 2.5]
    assert math.isclose(pre_crash[-1].survival, 0.5, abs_tol=1e-6)


def test_simultaneous_cashouts_drop_in_same_step(make_snapshot):
    snap = make_snapshot(crash=3.0, cashouts=[2.0, 2.0, 2.0, 2.0], alive=0)
    curve = survival_curve_for_round(snap)
    # Apenas dois pontos: (1.0, 1.0) e (2.0, 0.0)
    assert curve[0].multiplier == 1.0
    assert curve[1].multiplier == 2.0
    assert math.isclose(curve[1].survival, 0.0)


def test_aggregate_curve_weights_by_population(make_snapshot):
    """Rodada com mais jogadores deve dominar a média."""
    s_big = make_snapshot(
        round_id="big",
        crash=5.0,
        cashouts=[1.2] * 90,  # 90/100 cashearam cedo
        alive=10,
    )
    s_small = make_snapshot(
        round_id="small",
        crash=5.0,
        cashouts=[3.0] * 5,  # 5/5 cashearam tarde
        alive=0,
    )
    curve = aggregate_survival_curve([s_big, s_small], grid_step=0.5, grid_max=4.0)
    # Em m=2.0: na rodada big, sobreviveram 10/100; na small, 5/5.
    # Total alive = 15; total initial = 105; S ≈ 0.143
    point_2 = next(p for p in curve if math.isclose(p.multiplier, 2.0))
    assert 0.10 < point_2.survival < 0.20


def test_aggregate_empty_returns_empty():
    assert aggregate_survival_curve([]) == []
