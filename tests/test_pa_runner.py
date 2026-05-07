"""Testes do runner de player analytics (parte que não depende de Playwright)."""

from __future__ import annotations

import json

from app.player_analytics.runner import replay_session, replay_sync
from app.player_analytics.storage import load_all_snapshots


def _full_round(round_id="r1", crash=2.0):
    return [
        json.dumps({"type": "bet", "round_id": round_id, "user_id": "alice", "amount": 10.0}),
        json.dumps({"type": "bet", "round_id": round_id, "user_id": "bob", "amount": 20.0}),
        json.dumps({"round_id": round_id, "user_id": "alice", "cashout": 1.5}),
        json.dumps({"round_id": round_id, "crash_point": crash}),
    ]


async def test_replay_session_persists_when_enabled(in_memory_db):
    metrics = await replay_session(_full_round("r1", 2.0), persist=True)
    assert metrics.snapshots_generated == 1
    snaps = load_all_snapshots()
    assert len(snaps) == 1
    assert snaps[0].round_id == "r1"


async def test_replay_session_dry_run_does_not_persist(in_memory_db):
    metrics = await replay_session(_full_round("r1", 2.0), persist=False)
    assert metrics.snapshots_generated == 1
    # Banco deve permanecer vazio.
    assert load_all_snapshots() == []


async def test_replay_session_handles_multiple_rounds(in_memory_db):
    payloads = [
        *_full_round("r1", 1.5),
        *_full_round("r2", 3.0),
        *_full_round("r3", 1.1),
    ]
    metrics = await replay_session(payloads, persist=True)
    assert metrics.snapshots_generated == 3
    snaps = load_all_snapshots()
    assert {s.round_id for s in snaps} == {"r1", "r2", "r3"}


def test_replay_sync_wrapper_works(in_memory_db):
    """replay_sync é o entrypoint do Streamlit."""
    metrics = replay_sync(_full_round("r1", 2.0), persist=True)
    assert metrics.snapshots_generated == 1


async def test_replay_session_metrics_with_garbage_input():
    """Resiliência: input bagunçado não deve crashar; só não gera snapshot."""
    metrics = await replay_session(
        [
            "not json",
            b"\x00\x01garbage",
            json.dumps({"foo": "bar"}),  # JSON sem round_id
        ],
        persist=False,
    )
    assert metrics.snapshots_generated == 0
    assert metrics.frames_received == 3
    # Nenhum desses produz eventos válidos, então parse_failures fica em 0
    # (parser retorna [] em vez de raise).
    assert metrics.parse_failures == 0
