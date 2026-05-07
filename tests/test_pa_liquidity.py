"""Testes de liquidity exhaustion e player flow."""

from __future__ import annotations

from app.player_analytics.liquidity import (
    compute_liquidity,
    liquidity_trend,
    player_flow,
)


# ---------- compute_liquidity ----------

def test_liquidity_none_when_no_stakes(make_snapshot):
    snap = make_snapshot(crash=2.0, cashouts=[1.5], alive=0)
    m = compute_liquidity(snap)
    assert m.total_staked is None
    assert m.payout_ratio is None
    assert m.liquidity_exhaustion is None


def test_liquidity_exhaustion_computes_with_stakes(make_snapshot):
    # 2 jogadores, ambos cashearam em 2.0x com stake 10. Total staked=20,
    # paid=20*2.0=40 -> ratio=2.0 -> exhaustion clampado em 100.
    snap = make_snapshot(
        crash=3.0,
        cashouts=[2.0, 2.0],
        stakes=[10.0, 10.0],
    )
    m = compute_liquidity(snap)
    assert m.total_staked == 20.0
    assert m.total_paid_out == 40.0
    assert m.payout_ratio == 2.0
    assert m.liquidity_exhaustion == 100.0


def test_liquidity_zero_when_all_crash(make_snapshot):
    """Casa absorveu tudo: payout_ratio = 0."""
    snap = make_snapshot(
        crash=1.10,
        cashouts=[],  # ninguém cashou
        alive=2,
        stakes=[10.0, 10.0],
    )
    m = compute_liquidity(snap)
    assert m.payout_ratio == 0.0
    assert m.liquidity_exhaustion == 0.0


# ---------- player flow ----------

def test_flow_inflow(make_snapshot):
    a = make_snapshot(round_id="a", player_count=100, cashouts=[1.5] * 50, alive=50)
    b = make_snapshot(round_id="b", player_count=140, cashouts=[1.5] * 70, alive=70)
    flow = player_flow(a, b)
    assert flow.delta == 40
    assert flow.direction == "inflow"


def test_flow_outflow(make_snapshot):
    a = make_snapshot(round_id="a", player_count=100, cashouts=[1.5] * 50, alive=50)
    b = make_snapshot(round_id="b", player_count=70, cashouts=[1.5] * 35, alive=35)
    flow = player_flow(a, b)
    assert flow.delta == -30
    assert flow.direction == "outflow"


def test_flow_stable_within_threshold(make_snapshot):
    a = make_snapshot(round_id="a", player_count=100, cashouts=[1.5] * 50, alive=50)
    b = make_snapshot(round_id="b", player_count=102, cashouts=[1.5] * 51, alive=51)
    flow = player_flow(a, b)
    assert flow.direction == "stable"


def test_flow_zero_previous_does_not_crash(make_snapshot):
    a = make_snapshot(round_id="a", player_count=0, cashouts=[], alive=0)
    b = make_snapshot(round_id="b", player_count=10, cashouts=[1.5] * 5, alive=5)
    flow = player_flow(a, b)
    assert flow.delta == 10
    assert flow.relative_delta == 0.0


# ---------- liquidity trend ----------

def test_liquidity_trend_returns_window(make_snapshot):
    snaps = [
        make_snapshot(
            round_id=f"r{i}",
            crash=2.0,
            cashouts=[1.5, 1.5],
            stakes=[10.0, 10.0],
        )
        for i in range(5)
    ]
    trend = liquidity_trend(snaps, window=3)
    assert len(trend) == 3
    assert all(v is not None for v in trend)


def test_liquidity_trend_handles_missing_stakes(make_snapshot):
    """Mistura: rodadas com e sem stake."""
    snaps = [
        make_snapshot(round_id="r1", crash=2.0, cashouts=[1.5, 1.5], stakes=None),
        make_snapshot(
            round_id="r2",
            crash=2.0,
            cashouts=[1.5, 1.5],
            stakes=[10.0, 10.0],
        ),
    ]
    trend = liquidity_trend(snaps, window=2)
    assert trend[0] is None
    assert trend[1] is not None
