"""Testes do pipeline de eventos para snapshots."""

from __future__ import annotations

from datetime import datetime, timezone

from app.player_analytics.events import EventKind, PlayerEvent, RoundEvent
from app.player_analytics.pipeline import PlayerEventPipeline


def _round_start(rid="r1"):
    return RoundEvent(
        kind=EventKind.ROUND_START,
        round_id=rid,
        occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _round_crash(rid="r1", multiplier=2.5):
    return RoundEvent(
        kind=EventKind.ROUND_CRASH,
        round_id=rid,
        crash_multiplier=multiplier,
    )


def _bet(rid, anon, stake=10.0):
    return PlayerEvent(
        kind=EventKind.BET_PLACED, round_id=rid, anon_id=anon, stake=stake
    )


def _cashout(rid, anon, m=1.5, payout=None):
    return PlayerEvent(
        kind=EventKind.CASHOUT,
        round_id=rid,
        anon_id=anon,
        cashout_multiplier=m,
        payout=payout,
    )


# ---------- Pipeline básico ----------

def test_full_round_emits_one_snapshot():
    pipe = PlayerEventPipeline()
    events = [
        _round_start("r1"),
        _bet("r1", "a", 10.0),
        _bet("r1", "b", 20.0),
        _bet("r1", "c", 5.0),
        _cashout("r1", "a", 1.5),
        _cashout("r1", "b", 2.0),
        _round_crash("r1", multiplier=2.2),
    ]
    snaps = pipe.feed(events)
    assert len(snaps) == 1
    snap = snaps[0]
    assert snap.player_count == 3
    assert snap.cashed_out_count == 2
    assert snap.players_alive_at_crash == 1
    assert snap.crash_multiplier == 2.2
    assert snap.cashout_multipliers == (1.5, 2.0)
    assert snap.total_staked == 35.0


def test_payout_reconstructed_from_stake_and_multiplier():
    pipe = PlayerEventPipeline()
    events = [
        _round_start("r1"),
        _bet("r1", "a", 10.0),
        _cashout("r1", "a", 2.0, payout=None),  # sem payout explícito
        _round_crash("r1", multiplier=3.0),
    ]
    snaps = pipe.feed(events)
    # payout = 10 * 2 = 20
    assert snaps[0].total_paid_out == 20.0


def test_payout_uses_explicit_value_when_provided():
    pipe = PlayerEventPipeline()
    events = [
        _round_start("r1"),
        _bet("r1", "a", 10.0),
        _cashout("r1", "a", 2.0, payout=25.0),  # cassino calculou 25 (taxa?)
        _round_crash("r1", multiplier=3.0),
    ]
    snaps = pipe.feed(events)
    assert snaps[0].total_paid_out == 25.0


def test_dedup_within_round():
    """Mesmo jogador chegando por DOM e WS conta uma vez."""
    pipe = PlayerEventPipeline()
    events = [
        _round_start("r1"),
        _bet("r1", "a", 10.0),
        _bet("r1", "a", 10.0),  # duplicata
        _cashout("r1", "a", 1.5),
        _cashout("r1", "a", 1.5),  # duplicata
        _round_crash("r1", multiplier=2.0),
    ]
    snap = pipe.feed(events)[0]
    assert snap.player_count == 1
    assert snap.cashed_out_count == 1
    assert snap.players_alive_at_crash == 0


def test_out_of_order_events_handled():
    """Cashout antes de bet_placed deve funcionar (rodada criada lazily)."""
    pipe = PlayerEventPipeline()
    events = [
        _cashout("r1", "a", 1.5),
        _bet("r1", "a", 10.0),
        _round_crash("r1", multiplier=2.0),
    ]
    snap = pipe.feed(events)[0]
    assert snap.player_count == 1
    assert snap.cashed_out_count == 1


def test_no_round_start_still_works():
    """Coletor que perde o ROUND_START mas vê crash no fim."""
    pipe = PlayerEventPipeline()
    events = [
        _bet("r1", "a", 10.0),
        _bet("r1", "b", 20.0),
        _cashout("r1", "a", 1.8),
        _round_crash("r1", multiplier=2.5),
    ]
    snap = pipe.feed(events)[0]
    assert snap.player_count == 2


def test_crash_without_open_round_is_ignored():
    pipe = PlayerEventPipeline()
    snaps = pipe.feed([_round_crash("ghost", 2.0)])
    assert snaps == []


def test_crash_without_multiplier_is_dropped():
    pipe = PlayerEventPipeline()
    bad_crash = RoundEvent(kind=EventKind.ROUND_CRASH, round_id="r1")
    events = [_round_start("r1"), _bet("r1", "a", 10.0), bad_crash]
    snaps = pipe.feed(events)
    assert snaps == []


def test_callback_fires_on_close():
    received = []
    pipe = PlayerEventPipeline(on_snapshot=received.append)
    pipe.feed([
        _round_start("r1"),
        _bet("r1", "a", 10.0),
        _round_crash("r1", multiplier=1.5),
    ])
    assert len(received) == 1
    assert received[0].round_id == "r1"


def test_callback_exception_does_not_break_pipeline():
    def bad(_s):
        raise RuntimeError("boom")

    pipe = PlayerEventPipeline(on_snapshot=bad)
    snaps = pipe.feed([
        _round_start("r1"),
        _bet("r1", "a", 10.0),
        _round_crash("r1", multiplier=1.5),
    ])
    assert len(snaps) == 1


def test_max_open_rounds_evicts_oldest():
    """Não acumular memória se ROUND_CRASH não chega."""
    pipe = PlayerEventPipeline(max_open_rounds=3)
    # Abre 4 rodadas sem fechar
    for i in range(4):
        pipe.feed([_bet(f"r{i}", "a", 10.0)])
    assert len(pipe._open) == 3


def test_bet_without_amount_still_counts_player():
    pipe = PlayerEventPipeline()
    events = [
        _round_start("r1"),
        # bet sem stake
        PlayerEvent(kind=EventKind.BET_PLACED, round_id="r1", anon_id="a", stake=None),
        _round_crash("r1", multiplier=2.0),
    ]
    snap = pipe.feed(events)[0]
    assert snap.player_count == 1
    assert snap.total_staked is None  # sem volume agregado


def test_multiple_concurrent_rounds():
    pipe = PlayerEventPipeline()
    events = [
        _round_start("r1"),
        _round_start("r2"),
        _bet("r1", "a", 10.0),
        _bet("r2", "b", 20.0),
        _round_crash("r1", multiplier=1.5),
        _round_crash("r2", multiplier=3.0),
    ]
    snaps = pipe.feed(events)
    assert len(snaps) == 2
    by_id = {s.round_id: s for s in snaps}
    assert by_id["r1"].crash_multiplier == 1.5
    assert by_id["r2"].crash_multiplier == 3.0
