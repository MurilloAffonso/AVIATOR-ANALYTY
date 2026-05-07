"""Testes da camada de persistência de snapshots."""

from __future__ import annotations

from datetime import datetime, timezone

from app.player_analytics.events import RoundSnapshot
from app.player_analytics.storage import (
    load_all_snapshots,
    load_recent_snapshots,
    persist_snapshot,
)


def _snap(round_id: str, crash: float = 2.0) -> RoundSnapshot:
    started = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return RoundSnapshot(
        round_id=round_id,
        crash_multiplier=crash,
        started_at=started,
        ended_at=started,
        player_count=10,
        players_alive_at_crash=3,
        cashed_out_count=7,
        total_staked=100.0,
        total_paid_out=120.0,
        cashout_multipliers=(1.5, 1.5, 1.8, 1.8, 1.9, 1.9, 1.9),
        stakes=(10.0,) * 10,
    )


def test_persist_and_reload(in_memory_db):
    persist_snapshot(_snap("r1"))
    loaded = load_all_snapshots()
    assert len(loaded) == 1
    s = loaded[0]
    assert s.round_id == "r1"
    assert s.player_count == 10
    assert s.cashout_multipliers == (1.5, 1.5, 1.8, 1.8, 1.9, 1.9, 1.9)


def test_persist_idempotent_on_round_id(in_memory_db):
    """Mesmo round_id não duplica linhas (apenas atualiza)."""
    persist_snapshot(_snap("r1", crash=2.0))
    persist_snapshot(_snap("r1", crash=3.0))  # mesmo round_id, crash diferente
    loaded = load_all_snapshots()
    assert len(loaded) == 1
    assert loaded[0].crash_multiplier == 3.0


def test_load_recent_returns_in_desc_order(in_memory_db):
    from datetime import timedelta

    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        s = _snap(f"r{i}")
        s = RoundSnapshot(
            round_id=s.round_id,
            crash_multiplier=s.crash_multiplier,
            started_at=base + timedelta(minutes=i),
            ended_at=base + timedelta(minutes=i + 1),
            player_count=s.player_count,
            players_alive_at_crash=s.players_alive_at_crash,
            cashed_out_count=s.cashed_out_count,
            total_staked=s.total_staked,
            total_paid_out=s.total_paid_out,
            cashout_multipliers=s.cashout_multipliers,
            stakes=s.stakes,
        )
        persist_snapshot(s)
    recent = load_recent_snapshots(limit=3)
    assert [s.round_id for s in recent] == ["r4", "r3", "r2"]


def test_load_empty_returns_empty(in_memory_db):
    assert load_all_snapshots() == []
    assert load_recent_snapshots() == []


def test_persist_preserves_none_volumes(in_memory_db):
    """Cassino sem stake info → snapshot com None deve persistir como None."""
    started = datetime(2024, 1, 1, tzinfo=timezone.utc)
    s = RoundSnapshot(
        round_id="no-stakes",
        crash_multiplier=2.0,
        started_at=started,
        ended_at=started,
        player_count=5,
        players_alive_at_crash=2,
        cashed_out_count=3,
        total_staked=None,
        total_paid_out=None,
        cashout_multipliers=(1.5, 1.7, 1.9),
        stakes=(),
    )
    persist_snapshot(s)
    loaded = load_all_snapshots()[0]
    assert loaded.total_staked is None
    assert loaded.total_paid_out is None
    assert loaded.stakes == ()
