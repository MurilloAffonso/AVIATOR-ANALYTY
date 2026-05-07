"""Testes da PlayerAnalyticsBridge."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.collector.ws_collector import WebSocketCollector
from app.player_analytics.bridge import PlayerAnalyticsBridge
from app.player_analytics.events import (
    EventKind,
    PlayerEvent,
    RoundEvent,
    RoundSnapshot,
)


# ---------- helpers ----------


def _bet(round_id, anon_id, stake=10.0):
    return {
        "type": "bet",
        "round_id": round_id,
        "user_id": anon_id,
        "amount": stake,
    }


def _cashout(round_id, anon_id, m, payout=None):
    out = {
        "round_id": round_id,
        "user_id": anon_id,
        "cashout": m,
    }
    if payout is not None:
        out["payout"] = payout
    return out


def _crash(round_id, multiplier):
    return {"round_id": round_id, "crash_point": multiplier}


def _full_round_payloads(round_id="r1", crash=2.0):
    return [
        json.dumps(_bet(round_id, "alice", 10.0)),
        json.dumps(_bet(round_id, "bob", 20.0)),
        json.dumps(_cashout(round_id, "alice", 1.5)),
        json.dumps(_crash(round_id, crash)),
    ]


# ---------- ciclo de vida ----------


async def test_start_is_idempotent():
    bridge = PlayerAnalyticsBridge()
    await bridge.start()
    await bridge.start()  # não levanta
    await bridge.stop()


async def test_stop_is_idempotent():
    bridge = PlayerAnalyticsBridge()
    await bridge.stop()  # antes de start
    await bridge.start()
    await bridge.stop()
    await bridge.stop()  # após stop


async def test_on_frame_silently_drops_when_not_running():
    bridge = PlayerAnalyticsBridge()
    # Sem start: nada deve ir pra fila, mas nada deve crashar.
    bridge.on_frame(json.dumps(_crash("r1", 2.0)), "rx")
    assert bridge.metrics.frames_received == 1
    assert bridge.metrics.events_parsed == 0


# ---------- caminho feliz ----------


async def test_full_round_produces_snapshot():
    captured: list[RoundSnapshot] = []
    bridge = PlayerAnalyticsBridge(on_snapshot=captured.append)
    await bridge.start()
    try:
        await bridge.replay(_full_round_payloads("r1", crash=2.5))
    finally:
        await bridge.stop()

    assert len(captured) == 1
    snap = captured[0]
    assert snap.round_id == "r1"
    assert snap.crash_multiplier == 2.5
    assert snap.player_count == 2
    assert snap.cashed_out_count == 1
    assert snap.players_alive_at_crash == 1
    assert bridge.metrics.snapshots_generated == 1
    assert bridge.metrics.events_parsed >= 4


async def test_metrics_count_each_event():
    bridge = PlayerAnalyticsBridge()
    await bridge.start()
    try:
        await bridge.replay([
            json.dumps(_bet("r1", "alice", 10.0)),
            json.dumps(_bet("r1", "bob", 20.0)),
            json.dumps(_cashout("r1", "alice", 1.5)),
            json.dumps(_crash("r1", 2.0)),
        ])
    finally:
        await bridge.stop()

    # 2 bets + 1 cashout + 1 crash = 4 eventos válidos
    assert bridge.metrics.events_parsed == 4
    assert bridge.metrics.frames_received == 4
    assert bridge.metrics.parse_failures == 0


# ---------- tolerância a falhas ----------


async def test_unparseable_frame_is_silently_skipped():
    bridge = PlayerAnalyticsBridge()
    await bridge.start()
    try:
        await bridge.replay([
            "not json at all",
            b"\xff\xfe binary garbage",
            json.dumps({"foo": "bar"}),  # JSON sem round_id
            json.dumps(_crash("r1", 2.0)),
        ])
    finally:
        await bridge.stop()

    # Nenhum dos três primeiros gera evento, mas também não derruba
    # nada. parse_failures fica 0 porque o parser devolve [] em vez de
    # exceção — comportamento desejado.
    assert bridge.metrics.events_parsed == 1
    assert bridge.metrics.frames_received == 4
    assert bridge.metrics.parse_failures == 0


async def test_parse_failure_counted_when_parser_raises(monkeypatch):
    """Se o parser por algum motivo raise (não retornar []), contamos."""
    from app.player_analytics import bridge as bridge_mod

    def boom(_payload):
        raise RuntimeError("simulated parser bug")

    monkeypatch.setattr(bridge_mod, "parse_ws_frame_for_events", boom)

    bridge = PlayerAnalyticsBridge()
    await bridge.start()
    try:
        await bridge.replay(["whatever"])
    finally:
        await bridge.stop()

    assert bridge.metrics.parse_failures == 1
    assert bridge.metrics.last_error is not None
    assert "simulated parser bug" in bridge.metrics.last_error


async def test_user_callback_exception_does_not_break_consumer():
    """Snapshot callback que crasha não pode quebrar a bridge."""
    calls = []

    def bad(snap):
        calls.append(snap)
        raise RuntimeError("boom")

    bridge = PlayerAnalyticsBridge(on_snapshot=bad)
    await bridge.start()
    try:
        await bridge.replay(_full_round_payloads("r1"))
        # Segunda rodada também deve fluir mesmo após callback ruim.
        await bridge.replay(_full_round_payloads("r2"))
    finally:
        await bridge.stop()

    assert len(calls) == 2
    assert bridge.metrics.snapshots_generated == 2
    assert bridge.metrics.last_error is not None


async def test_pipeline_handle_exception_is_isolated(monkeypatch):
    bridge = PlayerAnalyticsBridge()
    await bridge.start()
    try:
        # Patcha o handle do pipeline para falhar uma vez.
        original = bridge._pipeline.handle
        calls = {"n": 0}

        def flaky(event):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return original(event)

        bridge._pipeline.handle = flaky

        await bridge.replay(_full_round_payloads("r1"))
    finally:
        await bridge.stop()

    # Mesmo com 1 falha, consumer não morre; conta restart.
    assert bridge.metrics.consumer_restarts >= 1


# ---------- back-pressure ----------


async def test_drop_oldest_when_queue_full(monkeypatch):
    """Fila apertada força drop-oldest e contagem."""
    captured: list[RoundSnapshot] = []
    bridge = PlayerAnalyticsBridge(
        on_snapshot=captured.append,
        queue_capacity=2,  # propositalmente apertado
    )
    await bridge.start()

    # Pausamos o consumer para que a fila encha de verdade.
    consumer = bridge._consumer_task
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    try:
        # Empurra 5 eventos sem ninguém consumir.
        for i in range(5):
            bridge.on_frame(json.dumps(_bet("r1", f"u{i}", 10.0)), "rx")
            await asyncio.sleep(0)  # deixa o call_soon_threadsafe rodar
    finally:
        # Não chama stop() normal pq mexemos no consumer; encerra fila.
        bridge._running = False

    # Capacidade=2, 5 enviados -> 3 dropped.
    assert bridge.metrics.dropped_oldest >= 1
    assert bridge.metrics.events_parsed == 5  # parse foi feito antes do enqueue


async def test_queue_size_reflects_pending_work():
    bridge = PlayerAnalyticsBridge(queue_capacity=100)
    await bridge.start()

    # Pausa consumer para acumular itens.
    consumer = bridge._consumer_task
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    try:
        for i in range(5):
            bridge.on_frame(json.dumps(_bet("r1", f"u{i}")), "rx")
            await asyncio.sleep(0)
    finally:
        bridge._running = False

    assert bridge.metrics.analytics_queue_size == 5


# ---------- direction filter ----------


async def test_outbound_frames_are_ignored():
    """frames sent (tx) vêm da página, não do cassino → ignorar."""
    bridge = PlayerAnalyticsBridge()
    await bridge.start()
    try:
        bridge.on_frame(json.dumps(_crash("r1", 2.0)), "tx")
        await asyncio.sleep(0)
    finally:
        await bridge.stop()

    # Conta como frame recebido (estatística honesta) mas NÃO como evento parseado.
    assert bridge.metrics.frames_received == 1
    assert bridge.metrics.events_parsed == 0


# ---------- replay ----------


async def test_replay_requires_started_bridge():
    bridge = PlayerAnalyticsBridge()
    with pytest.raises(RuntimeError):
        await bridge.replay(["whatever"])


async def test_replay_preserves_round_ordering():
    """Múltiplas rodadas em replay não devem misturar players."""
    captured: list[RoundSnapshot] = []
    bridge = PlayerAnalyticsBridge(on_snapshot=captured.append)
    await bridge.start()
    try:
        payloads = [
            *_full_round_payloads("r1", crash=1.5),
            *_full_round_payloads("r2", crash=3.0),
        ]
        await bridge.replay(payloads)
    finally:
        await bridge.stop()

    assert len(captured) == 2
    by_id = {s.round_id: s for s in captured}
    assert by_id["r1"].crash_multiplier == 1.5
    assert by_id["r2"].crash_multiplier == 3.0


async def test_replay_accepts_bytes_payloads():
    bridge = PlayerAnalyticsBridge()
    await bridge.start()
    try:
        payloads = [p.encode("utf-8") for p in _full_round_payloads("r1", 2.0)]
        await bridge.replay(payloads)
    finally:
        await bridge.stop()

    assert bridge.metrics.snapshots_generated == 1


# ---------- integração com WebSocketCollector ----------


async def test_listener_registration_on_ws_collector():
    """A bridge deve plugar limpo no WebSocketCollector via add_frame_listener."""
    captured: list[RoundSnapshot] = []
    bridge = PlayerAnalyticsBridge(on_snapshot=captured.append)
    await bridge.start()

    collector = WebSocketCollector(url="https://example.com")
    collector.add_frame_listener(bridge.on_frame)

    try:
        # Simula o Playwright entregando frames invocando _on_frame
        # diretamente — não dependemos de browser real.
        for payload in _full_round_payloads("r1", crash=2.0):
            collector._on_frame(payload, "rx")
            await asyncio.sleep(0)
        # dá tempo do consumer drenar
        await bridge._queue.join()
    finally:
        await bridge.stop()

    assert len(captured) == 1
    assert captured[0].round_id == "r1"


async def test_listener_failure_does_not_break_collector():
    """Se a bridge falhar, o coletor não pode quebrar."""

    def explode(_payload, _direction):
        raise RuntimeError("listener exploded")

    collector = WebSocketCollector(url="https://example.com")
    collector.add_frame_listener(explode)

    # Não deve raise — listeners são isolados.
    collector._on_frame(json.dumps(_crash("r1", 2.0)), "rx")
    # E o caminho principal segue: o buffer interno deve ter o multiplicador.
    assert collector._buffer == [2.0]


async def test_remove_frame_listener():
    collector = WebSocketCollector(url="https://example.com")
    calls = []

    def listener(payload, direction):
        calls.append((payload, direction))

    collector.add_frame_listener(listener)
    collector._on_frame("ignored", "rx")
    assert len(calls) == 1

    collector.remove_frame_listener(listener)
    collector._on_frame("ignored", "rx")
    assert len(calls) == 1  # não cresceu

    # Remover de novo é no-op (idempotente).
    collector.remove_frame_listener(listener)


# ---------- métricas ----------


async def test_metrics_dict_serializable():
    bridge = PlayerAnalyticsBridge()
    await bridge.start()
    try:
        await bridge.replay(_full_round_payloads("r1"))
    finally:
        await bridge.stop()

    d = bridge.metrics.as_dict()
    # Tem que ser JSON-serializável para logs estruturados.
    json.dumps(d)
    assert d["snapshots_generated"] == 1
    assert d["events_parsed"] >= 4


async def test_metrics_persist_after_stop():
    """Stop não zera contadores — operador precisa ler post-mortem."""
    bridge = PlayerAnalyticsBridge()
    await bridge.start()
    await bridge.replay(_full_round_payloads("r1"))
    await bridge.stop()

    assert bridge.metrics.snapshots_generated == 1
    assert bridge.metrics.events_parsed >= 4
