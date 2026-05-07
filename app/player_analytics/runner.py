"""Runner que integra coletores + bridge para uso na UI.

Encapsula a orquestração assíncrona em uma função síncrona para o
Streamlit. A bridge é instanciada localmente; suas métricas são
expostas no objeto retornado para a UI exibir após o término.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable, Optional

from app.collector.base import BaseCollector
from app.collector.dom_collector import DOMCollector
from app.collector.manager import CollectorManager
from app.collector.ws_collector import WebSocketCollector
from app.logging_config import get_logger
from app.player_analytics.bridge import BridgeMetrics, PlayerAnalyticsBridge
from app.player_analytics.storage import persist_snapshot


logger = get_logger("player_analytics.runner")


@dataclass
class RunResult:
    multipliers_saved: int
    bridge_metrics: BridgeMetrics


async def run_with_analytics(
    *,
    url: str,
    poll_seconds: float = 2.0,
    max_runtime: int = 0,
    headless: bool = False,
    enable_dom: bool = False,
) -> RunResult:
    """Executa coleta WS (+ DOM opcional) com a bridge ligada ao pipeline.

    A bridge:
    - escuta ``WebSocketCollector.add_frame_listener``;
    - drena eventos numa fila assíncrona dedicada;
    - alimenta um ``PlayerEventPipeline`` que persiste cada
      :class:`RoundSnapshot` no SQLite via ``persist_snapshot``.

    Args:
        url: URL do cassino.
        poll_seconds: intervalo de polling do DOM (se habilitado).
        max_runtime: tempo máximo (0 = sem limite).
        headless: se ``True``, navegador sem UI.
        enable_dom: se ``True``, sobe também o DOMCollector em paralelo.

    Returns:
        :class:`RunResult` com o número de multiplicadores persistidos
        e as métricas finais da bridge.
    """
    ws_collector = WebSocketCollector(
        url=url,
        max_runtime_seconds=max_runtime,
        headless=headless,
    )

    bridge = PlayerAnalyticsBridge(
        on_snapshot=persist_snapshot,
        queue_capacity=2048,
    )
    await bridge.start()

    # Plug listener: o coletor passa cada frame bruto para a bridge,
    # em paralelo ao caminho de extração de multiplicadores.
    ws_collector.add_frame_listener(bridge.on_frame)

    collectors: list[BaseCollector] = [ws_collector]
    if enable_dom:
        collectors.append(
            DOMCollector(
                url=url,
                poll_interval_seconds=poll_seconds,
                max_runtime_seconds=max_runtime,
                headless=headless,
            )
        )

    manager = CollectorManager(collectors)

    try:
        multipliers_saved = await manager.run()
    finally:
        # Garantir que a bridge drena tudo que ainda estiver na fila
        # antes de devolver o controle.
        await bridge.stop(drain=True)

    return RunResult(
        multipliers_saved=multipliers_saved,
        bridge_metrics=bridge.metrics,
    )


async def replay_session(
    payloads: Iterable[object],
    *,
    persist: bool = True,
) -> BridgeMetrics:
    """Replay offline de uma sessão WS gravada.

    Útil para validar mudanças de mapeamento de campos contra dados
    reais sem precisar de browser ou cassino.

    Args:
        payloads: iterável de payloads (str/bytes/dict) na ordem
            cronológica em que foram recebidos.
        persist: se ``True``, persiste snapshots no SQLite local. Se
            ``False`` (modo dry-run), apenas computa métricas.
    """
    callback = persist_snapshot if persist else None
    bridge = PlayerAnalyticsBridge(on_snapshot=callback)
    await bridge.start()
    try:
        await bridge.replay(payloads)
    finally:
        await bridge.stop(drain=True)
    return bridge.metrics


def run_sync(
    url: str,
    *,
    poll_seconds: float = 2.0,
    max_runtime: int = 0,
    headless: bool = False,
    enable_dom: bool = False,
) -> RunResult:
    """Wrapper síncrono para Streamlit (que não roda async)."""
    return asyncio.run(
        run_with_analytics(
            url=url,
            poll_seconds=poll_seconds,
            max_runtime=max_runtime,
            headless=headless,
            enable_dom=enable_dom,
        )
    )


def replay_sync(
    payloads: Iterable[object], *, persist: bool = True
) -> BridgeMetrics:
    return asyncio.run(replay_session(payloads, persist=persist))
