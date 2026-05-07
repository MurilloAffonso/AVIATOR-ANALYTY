"""Bridge entre o WebSocketCollector e o PlayerEventPipeline.

Topologia::

    Playwright ws.framereceived
              │  (callback síncrono)
              ▼
    bridge._on_frame(payload, direction)         <-- listener registrado
              │
              │  parse_ws_frame_for_events(payload)
              │  events: [RoundEvent | PlayerEvent | ...]
              ▼
    asyncio.Queue[Event]   (bounded, drop-oldest quando cheia)
              │
              ▼
    consumer task (async)
              │
              │  pipeline.handle(event)
              ▼
    PlayerEventPipeline -> on_snapshot(snapshot)

Garantias:

- O listener síncrono é não-bloqueante: parseia, tenta enfileirar; se
  cheia, descarta o item mais antigo e incrementa ``dropped_oldest``.
- O caminho de multiplicadores do ``WebSocketCollector`` continua
  intacto. A bridge é puramente aditiva.
- Falhas isoladas: parse failure, listener exception, callback
  exception — todas registradas em métricas e logs, nunca propagam.
- ``stop()`` é idempotente. ``start()`` é idempotente.
- Suporta ``replay`` de uma sequência de payloads gravada — útil para
  debug, validação de cassinos novos e regression testing.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Optional

from app.logging_config import get_logger
from app.player_analytics.events import (
    EventKind,
    PlayerEvent,
    RoundEvent,
    RoundSnapshot,
)
from app.player_analytics.pipeline import PlayerEventPipeline
from app.player_analytics.ws_adapter import parse_ws_frame_for_events


SnapshotCallback = Callable[[RoundSnapshot], None]


@dataclass
class BridgeMetrics:
    """Métricas operacionais da bridge.

    Acessível em runtime via ``bridge.metrics`` para a UI ou logs
    estruturados. Todos os campos são contadores monotônicos exceto
    ``analytics_queue_size``, que é uma amostra do tamanho atual.
    """

    frames_received: int = 0
    events_parsed: int = 0
    parse_failures: int = 0
    enqueue_failures: int = 0
    dropped_oldest: int = 0
    analytics_queue_size: int = 0
    snapshots_generated: int = 0
    consumer_restarts: int = 0
    last_error: Optional[str] = None

    def as_dict(self) -> dict[str, object]:
        return {
            "frames_received": self.frames_received,
            "events_parsed": self.events_parsed,
            "parse_failures": self.parse_failures,
            "enqueue_failures": self.enqueue_failures,
            "dropped_oldest": self.dropped_oldest,
            "analytics_queue_size": self.analytics_queue_size,
            "snapshots_generated": self.snapshots_generated,
            "consumer_restarts": self.consumer_restarts,
            "last_error": self.last_error,
        }


# Sentinela para sinalizar fim de fila ao consumidor.
_STOP_SIGNAL: object = object()


class PlayerAnalyticsBridge:
    """Liga frames WebSocket ao pipeline de player analytics.

    Args:
        pipeline: ``PlayerEventPipeline`` que processa os eventos
            decodificados. Se ``None``, é criado um novo internamente.
        on_snapshot: callback síncrono chamado a cada rodada fechada;
            tipicamente ``persist_snapshot`` da camada de storage.
        queue_capacity: tamanho máximo da fila assíncrona. Quando cheia,
            descarta o item mais antigo (drop-oldest) para preservar a
            ponta recente, que costuma conter o crash da rodada.
    """

    def __init__(
        self,
        *,
        pipeline: Optional[PlayerEventPipeline] = None,
        on_snapshot: Optional[SnapshotCallback] = None,
        queue_capacity: int = 1024,
    ) -> None:
        self._on_snapshot_user = on_snapshot
        self._pipeline = pipeline or PlayerEventPipeline(
            on_snapshot=self._wrapped_snapshot_callback
        )
        # Se o pipeline foi fornecido pelo usuário, embrulhamos o
        # callback dele para que ainda atualizemos métricas.
        if pipeline is not None:
            self._wrap_existing_pipeline(pipeline)

        self._queue_capacity = queue_capacity
        self._queue: Optional[asyncio.Queue] = None

        self._consumer_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._lock = threading.Lock()  # protege contadores cruzando threads
        self._logger = get_logger("player_analytics.bridge")

        self.metrics = BridgeMetrics()

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    async def start(self) -> None:
        """Inicia o consumer task. Idempotente."""
        if self._running:
            return
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._queue_capacity)
        self._consumer_task = asyncio.create_task(
            self._consume_loop(), name="player-analytics-bridge-consumer"
        )
        self._running = True
        self._logger.info(
            "bridge iniciada",
            extra={"queue_capacity": self._queue_capacity},
        )

    async def stop(self, *, drain: bool = True) -> None:
        """Para o consumer e drena a fila se ``drain=True``. Idempotente."""
        if not self._running or self._queue is None:
            return
        self._running = False

        if drain:
            # Sinaliza fim e aguarda o consumer drenar tudo.
            await self._queue.put(_STOP_SIGNAL)
            if self._consumer_task is not None:
                try:
                    await asyncio.wait_for(self._consumer_task, timeout=5.0)
                except asyncio.TimeoutError:
                    self._logger.warning(
                        "consumer não terminou a tempo; cancelando"
                    )
                    self._consumer_task.cancel()
        else:
            if self._consumer_task is not None:
                self._consumer_task.cancel()
                try:
                    await self._consumer_task
                except asyncio.CancelledError:
                    pass

        self._consumer_task = None
        self._queue = None
        self._logger.info(
            "bridge parada",
            extra=self.metrics.as_dict(),
        )

    # ---------------------------------------------------------------
    # Frame ingestion (chamado pelo WebSocketCollector)
    # ---------------------------------------------------------------

    def on_frame(self, payload: object, direction: str = "rx") -> None:
        """Listener síncrono. Plug em ``WebSocketCollector.add_frame_listener``.

        Faz o parsing inline (rápido, CPU-bound apenas) e enfileira os
        eventos. Nunca bloqueia. Falhas são contidas e contabilizadas.
        """
        with self._lock:
            self.metrics.frames_received += 1

        if not self._running or self._queue is None or self._loop is None:
            # Bridge não está ativa — descartamos silenciosamente.
            return

        # Apenas frames recebidos contam para análise; frames enviados
        # vêm da página (login, heartbeat) e nunca contêm dados que nos
        # interessem.
        if direction != "rx":
            return

        try:
            events = parse_ws_frame_for_events(payload)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.metrics.parse_failures += 1
                self.metrics.last_error = f"parse: {exc!r}"
            self._logger.debug("parse_ws_frame_for_events falhou: %s", exc)
            return

        if not events:
            return

        with self._lock:
            self.metrics.events_parsed += len(events)

        # Empurra cada evento. Como estamos num callback síncrono
        # potencialmente vindo de outra thread (Playwright), usamos
        # call_soon_threadsafe.
        for event in events:
            self._loop.call_soon_threadsafe(self._enqueue_or_drop, event)

    def _enqueue_or_drop(self, event: object) -> None:
        """Tenta enfileirar; se cheio, descarta o mais antigo."""
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop-oldest: tira a frente e tenta de novo.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                with self._lock:
                    self.metrics.dropped_oldest += 1
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                with self._lock:
                    self.metrics.enqueue_failures += 1
                self._logger.warning(
                    "enqueue falhou mesmo após drop_oldest",
                    extra=self.metrics.as_dict(),
                )

        with self._lock:
            self.metrics.analytics_queue_size = self._queue.qsize()

    # ---------------------------------------------------------------
    # Replay
    # ---------------------------------------------------------------

    async def replay(self, payloads: Iterable[object]) -> None:
        """Re-injeta uma sequência de payloads gravados.

        Útil para debug, regressão e validação de cassinos novos sem
        precisar de browser. Aceita strings, bytes ou já dicionários
        (caso já tenha decodificado).

        Os payloads passam pelo mesmo caminho de ``on_frame`` (parse +
        enqueue + consumer). A bridge precisa estar iniciada
        (``await start()``).
        """
        if not self._running or self._queue is None:
            raise RuntimeError("bridge não iniciada; chame start() antes de replay()")

        for payload in payloads:
            self.on_frame(payload, "rx")
            # Cede para o consumer drenar entre frames; preserva ordem
            # de causalidade entre rodadas mesmo em replay rápido.
            await asyncio.sleep(0)

        # Espera a fila esvaziar para que callers possam inspecionar
        # snapshots.
        await self._queue.join()

    # ---------------------------------------------------------------
    # Consumer loop
    # ---------------------------------------------------------------

    async def _consume_loop(self) -> None:
        """Drena a fila e alimenta o pipeline. Resiliente a exceções."""
        assert self._queue is not None
        while True:
            try:
                event = await self._queue.get()
            except asyncio.CancelledError:
                raise

            if event is _STOP_SIGNAL:
                self._queue.task_done()
                break

            try:
                self._pipeline.handle(event)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.metrics.last_error = f"pipeline: {exc!r}"
                    self.metrics.consumer_restarts += 1
                self._logger.exception("pipeline.handle falhou")
            finally:
                self._queue.task_done()
                with self._lock:
                    self.metrics.analytics_queue_size = self._queue.qsize()

    # ---------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------

    def _wrapped_snapshot_callback(self, snapshot: RoundSnapshot) -> None:
        """Wrapper que conta snapshots e delega ao callback do usuário."""
        with self._lock:
            self.metrics.snapshots_generated += 1
        self._logger.info(
            "snapshot gerado",
            extra={
                "round_id": snapshot.round_id,
                "player_count": snapshot.player_count,
                "crash": snapshot.crash_multiplier,
                "metrics": self.metrics.as_dict(),
            },
        )
        if self._on_snapshot_user is not None:
            try:
                self._on_snapshot_user(snapshot)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.metrics.last_error = f"on_snapshot: {exc!r}"
                self._logger.exception("on_snapshot do usuário falhou")

    def _wrap_existing_pipeline(self, pipeline: PlayerEventPipeline) -> None:
        """Embrulha o on_snapshot de um pipeline pré-existente.

        Necessário quando o usuário passou um pipeline já configurado
        no construtor — ainda precisamos contar snapshots e logar.
        """
        original = pipeline._on_snapshot  # noqa: SLF001 (interno consciente)

        def wrapped(snapshot: RoundSnapshot) -> None:
            with self._lock:
                self.metrics.snapshots_generated += 1
            self._logger.info(
                "snapshot gerado",
                extra={
                    "round_id": snapshot.round_id,
                    "player_count": snapshot.player_count,
                    "crash": snapshot.crash_multiplier,
                },
            )
            try:
                original(snapshot)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.metrics.last_error = f"on_snapshot: {exc!r}"
                self._logger.exception("on_snapshot original falhou")

        pipeline._on_snapshot = wrapped  # noqa: SLF001
