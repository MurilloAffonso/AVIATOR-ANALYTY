"""Testes do adapter de frames WS para eventos de domínio."""

from __future__ import annotations

import json

from app.player_analytics.events import EventKind, PlayerEvent, RoundEvent
from app.player_analytics.ws_adapter import parse_ws_frame_for_events


def test_empty_frame_returns_empty():
    assert parse_ws_frame_for_events("") == []
    assert parse_ws_frame_for_events(b"") == []


def test_non_json_returns_empty():
    assert parse_ws_frame_for_events("hello world") == []


def test_frame_without_round_id_returns_empty():
    """Sem round_id não dá pra atribuir evento; descarta."""
    payload = json.dumps({"multiplier": 2.5, "user": "x"})
    assert parse_ws_frame_for_events(payload) == []


def test_round_crash_extracted():
    payload = json.dumps({"round_id": "r1", "crash_point": 3.45})
    events = parse_ws_frame_for_events(payload)
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, RoundEvent)
    assert e.kind is EventKind.ROUND_CRASH
    assert e.round_id == "r1"
    assert e.crash_multiplier == 3.45


def test_bet_placed_extracted_with_anon_id():
    payload = json.dumps({
        "type": "bet_placed",
        "round_id": "r1",
        "user_id": "user-42",
        "amount": 25.0,
    })
    events = parse_ws_frame_for_events(payload)
    bets = [e for e in events if isinstance(e, PlayerEvent)
            and e.kind is EventKind.BET_PLACED]
    assert len(bets) == 1
    assert bets[0].stake == 25.0
    assert len(bets[0].anon_id) == 16  # hash truncado
    # Mesmo user_id sempre produz o mesmo anon_id.
    again = parse_ws_frame_for_events(payload)[0]
    assert again.anon_id == bets[0].anon_id


def test_cashout_extracted_with_payout():
    payload = json.dumps({
        "round_id": "r1",
        "user_id": "user-42",
        "cashout": 2.5,
        "payout": 50.0,
    })
    events = parse_ws_frame_for_events(payload)
    cashouts = [e for e in events if isinstance(e, PlayerEvent)
                and e.kind is EventKind.CASHOUT]
    assert len(cashouts) == 1
    assert cashouts[0].cashout_multiplier == 2.5
    assert cashouts[0].payout == 50.0


def test_array_of_events():
    payload = json.dumps([
        {"round_id": "r1", "user_id": "a", "amount": 10.0, "type": "bet"},
        {"round_id": "r1", "user_id": "b", "amount": 20.0, "type": "bet"},
    ])
    events = parse_ws_frame_for_events(payload)
    assert len(events) == 2


def test_wrapped_under_data_field():
    """Muitas APIs aninham o evento sob 'data' ou 'payload'."""
    payload = json.dumps({
        "channel": "rounds",
        "data": {"round_id": "r1", "crash_point": 1.5},
    })
    events = parse_ws_frame_for_events(payload)
    assert len(events) == 1
    assert isinstance(events[0], RoundEvent)


def test_custom_field_map_via_env(monkeypatch):
    """Cassino com nomes próprios de campo: configurar via env var."""
    monkeypatch.setenv(
        "AVIATOR_PA_FIELD_MAP",
        "round_id=gameRoundUUID,player_id=accountHash,stake=wagerCents",
    )
    payload = json.dumps({
        "type": "bet",
        "gameRoundUUID": "abc123",
        "accountHash": "h-99",
        "wagerCents": 1500,
    })
    events = parse_ws_frame_for_events(payload)
    bets = [e for e in events if isinstance(e, PlayerEvent)]
    assert len(bets) == 1
    assert bets[0].round_id == "abc123"
    assert bets[0].stake == 1500


def test_unknown_payload_does_not_crash():
    """Estrutura completamente diferente: vazio, sem stack trace."""
    payload = json.dumps({"foo": "bar", "baz": [1, 2, 3]})
    assert parse_ws_frame_for_events(payload) == []


def test_invalid_bytes_returns_empty():
    assert parse_ws_frame_for_events(b"\xff\xfe") == []


def test_anon_id_does_not_leak_raw_id():
    """Garantia: o ID original não aparece no anon_id."""
    payload = json.dumps({
        "type": "bet",
        "round_id": "r1",
        "user_id": "sensitive-username-john-doe",
        "amount": 10.0,
    })
    events = parse_ws_frame_for_events(payload)
    bet = events[0]
    assert "sensitive" not in bet.anon_id
    assert "john" not in bet.anon_id
    assert "doe" not in bet.anon_id
