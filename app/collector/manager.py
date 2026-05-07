"""Orquestrador de coletores.

Responsabilidades:
- Subir N coletores em paralelo (DOM, WS, ou ambos).
- Drenar a fila assíncrona de eventos.
- Aplicar deduplicação cross-source (mesmo multiplicador chegando por
  DOM e por WS é gravado uma vez só, dentro de uma janela curta).
- Persistir os multiplicadores aceitos no banco SQLite.

Garantia: o manager *também* não toma nenhuma ação financeira. Apenas lê
da fila e escreve no banco de leitura.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from typing import Optional

from app.analyzer import categorize_multiplier
from app.collector.base import BaseCollector, CollectorEvent
from app.collector.dedup import find_new_items
from app.database import SessionLocal
from app.logging_config import get_logger
from app.models import RoundResult


# Janela de cross-dedup: multiplicadores idênticos vindos de fontes diferentes
# dentro deste intervalo são considerados a mesma rodada.
CROSS_SOURCE_DEDUP_WINDOW_SECONDS = 5.0

# Tamanho máximo do histórico recente mantido em memória pelo manager.
RECENT_HISTORY_CAP = 200


class CollectorManager:
    """Gerencia ciclo de vida de coletores e consome a fila de eventos.

    Uso típico:

        manager = CollectorManager([dom, ws])
        saved = await manager.run()

    """

    def __init__(
        self,
        collectors: Iterable[BaseCollector],
        queue_max_size: int = 1000,
    ) -> None:
        self._collectors = list(collectors)
        self._queue: asyncio.Queue[CollectorEvent] = asyncio.Queue(
            maxsize=queue_max_size
        )
        self._logger = get_logger("collector.manager")
        # Histórico recente para dedup cross-source: lista de (timestamp, valor).
        self._recent: list[tuple[float, float]] = []
        self._total_saved = 0

    @property
    def total_saved(self) -> int:
        return self._total_saved

    async def run(self) -> int:
        """Executa todos os coletores e o consumidor até todos pararem."""
        if not self._collectors:
            self._logger.warning("Nenhum coletor registrado.")
            return 0

        producers = [
            asyncio.create_task(c.run_async(self._queue), name=f"collector-{c.name}")
            for c in self._collectors
        ]

        consumer = asyncio.create_task(self._consume_loop(), name="manager-consumer")

        try:
            await asyncio.gather(*producers, return_exceptions=True)
        finally:
            # Espera o consumidor drenar o que ainda estiver na fila.
            await self._drain_remaining()
            consumer.cancel()
            try:
                await consumer
            except asyncio.CancelledError:
                pass

        self._logger.info(
            "Manager finalizado. Total persistido: %d", self._total_saved
        )
        return self._total_saved

    def request_stop(self) -> None:
        for c in self._collectors:
            c.request_stop()

    async def _consume_loop(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                self._handle_event(event)
            except Exception as exc:  # noqa: BLE001
                self._logger.exception("Falha ao processar evento: %s", exc)
            finally:
                self._queue.task_done()

    async def _drain_remaining(self) -> None:
        # Drena tudo que sobrou na fila depois que os produtores encerraram.
        while not self._queue.empty():
            event = self._queue.get_nowait()
            try:
                self._handle_event(event)
            except Exception as exc:  # noqa: BLE001
                self._logger.exception("Falha ao processar evento: %s", exc)
            finally:
                self._queue.task_done()

    def _handle_event(self, event: CollectorEvent) -> None:
        accepted = self._cross_source_dedup(event.multipliers)
        if not accepted:
            self._logger.debug(
                "evento descartado por cross-dedup: source=%s, n=%d",
                event.source,
                len(event.multipliers),
            )
            return

        saved = self._persist(accepted)
        self._total_saved += saved
        self._logger.info(
            "evento persistido: source=%s, recebidos=%d, salvos=%d",
            event.source,
            len(event.multipliers),
            saved,
        )

    def _cross_source_dedup(self, candidates: list[float]) -> list[float]:
        """Filtra valores que já vieram de outra fonte na janela recente.

        Para a maioria dos eventos do DOM, a "novidade" já foi calculada
        pelo próprio coletor. Aqui só protegemos contra a sobreposição
        DOM/WS para a mesma rodada.
        """
        now = time.time()
        # Limpa entradas velhas.
        cutoff = now - CROSS_SOURCE_DEDUP_WINDOW_SECONDS
        self._recent = [(t, v) for (t, v) in self._recent if t >= cutoff]

        accepted: list[float] = []
        recent_values = [v for (_, v) in self._recent]
        for value in candidates:
            normalized = round(value, 2)
            if _close_to_any(normalized, recent_values):
                continue
            accepted.append(normalized)
            self._recent.append((now, normalized))
            recent_values.append(normalized)

        # Trim memória.
        if len(self._recent) > RECENT_HISTORY_CAP:
            self._recent = self._recent[-RECENT_HISTORY_CAP:]
        return accepted

    def _persist(self, values: list[float]) -> int:
        if not values:
            return 0

        saved = 0
        with SessionLocal() as session:
            for value in values:
                if value < 1.0:
                    self._logger.warning(
                        "Ignorando valor fora do intervalo: %s", value
                    )
                    continue
                session.add(
                    RoundResult(
                        multiplier=value,
                        category=categorize_multiplier(value),
                    )
                )
                saved += 1
            session.commit()
        return saved


def _close_to_any(value: float, others: list[float], tol: float = 1e-6) -> bool:
    return any(abs(value - o) <= tol for o in others)


async def run_collectors(
    collectors: list[BaseCollector],
    queue_max_size: int = 1000,
) -> int:
    """Atalho funcional para subir um manager descartável."""
    manager = CollectorManager(collectors, queue_max_size=queue_max_size)
    return await manager.run()
