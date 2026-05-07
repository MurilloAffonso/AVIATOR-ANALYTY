"""Testes do BaseCollector e do CollectorManager.

Usa um coletor fake que produz uma sequência pré-definida de eventos,
sem Playwright nem rede. O foco é provar que:
- O contrato base é respeitado (publica eventos, respeita stop).
- O manager drena a fila e persiste corretamente.
- O cross-source dedup não duplica multiplicadores.
- O coletor real DOM não realiza ações financeiras (proibições no
  módulo, validadas por inspeção estática).
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app.collector.base import BaseCollector, CollectorEvent
from app.collector.manager import CollectorManager
from app.models import RoundResult


class FakeCollector(BaseCollector):
    """Coletor sintético: emite uma lista pré-definida de batches."""

    def __init__(self, name: str, batches: list[list[float]]):
        super().__init__()
        self.name = name
        self._batches = list(batches)

    async def run_async(self, queue):
        for batch in self._batches:
            if self.is_stopped:
                return
            await self.emit(queue, batch)
            await asyncio.sleep(0)  # cede para o consumer.


# ---------- BaseCollector ----------

def test_base_request_stop_sets_event():
    fc = FakeCollector("fake", [])
    assert fc.is_stopped is False
    fc.request_stop()
    assert fc.is_stopped is True


@pytest.mark.asyncio
async def test_emit_skips_empty_lists():
    fc = FakeCollector("fake", [])
    queue: asyncio.Queue = asyncio.Queue()
    await fc.emit(queue, [])
    assert queue.empty()


@pytest.mark.asyncio
async def test_emit_publishes_event():
    fc = FakeCollector("fake", [])
    queue: asyncio.Queue = asyncio.Queue()
    await fc.emit(queue, [1.5, 2.0])
    event: CollectorEvent = await queue.get()
    assert event.source == "fake"
    assert event.multipliers == [1.5, 2.0]


# ---------- CollectorManager ----------

@pytest.mark.asyncio
async def test_manager_persists_events(in_memory_db):
    fc = FakeCollector("fake", [[1.50, 2.00], [3.50]])
    manager = CollectorManager([fc])
    saved = await manager.run()
    assert saved == 3

    with in_memory_db() as session:
        rows = session.query(RoundResult).order_by(RoundResult.id).all()
    assert [r.multiplier for r in rows] == [1.50, 2.00, 3.50]


@pytest.mark.asyncio
async def test_manager_cross_source_dedup_avoids_duplicates(in_memory_db):
    """Mesmo valor chegando por DOM e WS na mesma janela: grava uma vez."""
    dom = FakeCollector("dom", [[2.50]])
    ws = FakeCollector("ws", [[2.50]])
    manager = CollectorManager([dom, ws])
    saved = await manager.run()
    # Apenas um persiste, o segundo cai no cross-source dedup.
    assert saved == 1


@pytest.mark.asyncio
async def test_manager_with_no_collectors_returns_zero():
    manager = CollectorManager([])
    saved = await manager.run()
    assert saved == 0


@pytest.mark.asyncio
async def test_manager_filters_invalid_multipliers(in_memory_db):
    fc = FakeCollector("fake", [[0.5, 2.0]])  # 0.5 deve ser ignorado.
    manager = CollectorManager([fc])
    saved = await manager.run()
    assert saved == 1


# ---------- Auditoria estática do DOMCollector ----------

def _strip_comments_and_strings(src: str) -> str:
    """Remove comentários e literais string para auditoria de chamadas reais.

    Usa o tokenizador padrão do Python para garantir precisão.
    """
    import io
    import tokenize

    out: list[str] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in tokens:
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except tokenize.TokenizeError:
        return src
    return " ".join(out)


def test_dom_collector_has_no_financial_actions():
    """Garantia automatizada: o código-fonte do DOMCollector não
    contém chamadas a APIs do Playwright que executam ações de UI
    (clique, digitação, envio de form).
    """
    from app.collector import dom_collector

    src = _strip_comments_and_strings(inspect.getsource(dom_collector))
    forbidden = [
        ".click(", ".dblclick(", ".tap(", ".press(", ".type(",
        ".fill(", ".hover(", ".select_option(",
        ".check(", ".uncheck(", ".dispatch_event(",
        ".set_input_files(", ".drag_to(",
    ]
    for token in forbidden:
        assert token not in src, (
            f"DOMCollector não pode chamar {token} (somente leitura)"
        )


def test_ws_collector_has_no_send_calls():
    """Garantia: o WebSocketCollector não envia frames."""
    from app.collector import ws_collector

    src = _strip_comments_and_strings(inspect.getsource(ws_collector))
    forbidden = ["ws.send(", "websocket.send(", "send_text(", "send_bytes("]
    for token in forbidden:
        assert token not in src, (
            f"WebSocketCollector não pode chamar {token} (somente leitura)"
        )
