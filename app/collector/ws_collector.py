"""Coletor passivo de frames WebSocket via Playwright (somente leitura).

Estratégia: o Playwright expõe ``page.on("websocket", ...)`` para
escutar conexões WS abertas pela aplicação. Para cada conexão,
registramos handlers em ``framereceived`` e ``framesent`` apenas para
*observar*. Nunca enviamos um frame, nunca chamamos ``send``.

Vantagens sobre o ``DOMCollector``:
- Captura rodadas mesmo quando o histórico do DOM ainda não atualizou.
- Latência menor.
- Não depende de o histórico estar visível na tela.

Garantias:
- Zero ações de UI (clique, digitação, navegação para botões de aposta).
- Zero envio de frames WS.
- Apenas extração estatística do payload bruto via ``parser``.

Pontos de extensão:
- ``add_frame_listener(callback)`` — outros componentes (ex.:
  ``PlayerAnalyticsBridge``) podem se inscrever para receber o payload
  bruto sem afetar o caminho principal de extração de multiplicadores.
  Listeners executam em try/except isolado: se um falhar, os outros
  e o próprio coletor seguem normais.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Optional

from app.collector.base import BaseCollector, CollectorEvent
from app.collector.parser import extract_from_ws_frame


# Tipo do listener externo: recebe (payload_bruto, direction)
FrameListener = Callable[[object, str], None]


class WebSocketCollector(BaseCollector):
    """Escuta frames WebSocket recebidos pela página e extrai multiplicadores.

    Args:
        url: URL inicial onde o jogo carrega (a conexão WS é estabelecida
            pela própria página, não pelo coletor).
        max_runtime_seconds: Tempo máximo de execução (0 = sem limite).
        headless: Se ``True``, navegador sem UI.
        flush_interval_seconds: Periodicidade de flush para o manager,
            agrupando multiplicadores observados desde o último flush.
    """

    name = "ws"

    def __init__(
        self,
        url: str,
        max_runtime_seconds: int = 0,
        headless: bool = False,
        flush_interval_seconds: float = 1.0,
    ) -> None:
        super().__init__()
        self.url = url
        self.max_runtime_seconds = max_runtime_seconds
        self.headless = headless
        self.flush_interval_seconds = flush_interval_seconds
        self._buffer: list[float] = []
        self._buffer_lock = asyncio.Lock()
        # Listeners externos para o payload bruto. Cada um é chamado em
        # try/except isolado em ``_on_frame``. Não afeta a extração de
        # multiplicadores — esse caminho permanece intocado.
        self._frame_listeners: list[FrameListener] = []

    def add_frame_listener(self, listener: FrameListener) -> None:
        """Registra um observador externo do payload bruto.

        O listener recebe ``(payload, direction)`` onde ``direction`` é
        ``"rx"`` (recebido) ou ``"tx"`` (enviado pela página, nunca por nós).
        Listeners não devem bloquear nem levantar exceções; ainda assim,
        falhas são contidas em try/except.
        """
        self._frame_listeners.append(listener)

    def remove_frame_listener(self, listener: FrameListener) -> None:
        """Remove um listener previamente registrado, se existir."""
        try:
            self._frame_listeners.remove(listener)
        except ValueError:
            pass

    async def run_async(self, queue: "asyncio.Queue[CollectorEvent]") -> None:
        try:
            from playwright.async_api import (
                Error as PlaywrightError,
                async_playwright,
            )
        except ImportError:
            self._logger.error(
                "Playwright não está instalado. Pule a coleta WS ou rode "
                "`pip install playwright && playwright install chromium`."
            )
            return

        self._logger.info("Iniciando WebSocketCollector: %s", self.url)
        start = time.time()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            page = await context.new_page()

            page.on("websocket", self._on_websocket)

            try:
                await page.goto(self.url, wait_until="domcontentloaded")
            except PlaywrightError as exc:
                self._logger.error("Falha ao abrir a URL: %s", exc)
                await browser.close()
                return

            self._logger.info(
                "Página aberta. Escutando frames WS (modo leitura passivo)."
            )

            while not self.is_stopped:
                if (
                    self.max_runtime_seconds > 0
                    and (time.time() - start) >= self.max_runtime_seconds
                ):
                    self._logger.info(
                        "Tempo máximo atingido. Encerrando WebSocketCollector."
                    )
                    break

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.flush_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass  # Ciclo normal de flush.

                await self._flush(queue)

            await self._flush(queue)  # Drena o que ficou no buffer.

            try:
                await context.close()
                await browser.close()
            except Exception:  # noqa: BLE001
                pass

        self._logger.info("WebSocketCollector finalizado.")

    def _on_websocket(self, ws) -> None:
        url = getattr(ws, "url", "<unknown>")
        self._logger.info("WebSocket detectado: %s", url)

        ws.on("framereceived", lambda payload: self._on_frame(payload, "rx"))
        # Observamos frames enviados *apenas para diagnóstico/log*.
        # Nunca chamamos ws.send() — esse é o ponto inteiro do "somente leitura".
        ws.on("framesent", lambda payload: self._logger.debug(
            "frame enviado pela página (não pelo coletor) bytes=%d",
            len(payload) if isinstance(payload, (bytes, str)) else 0,
        ))
        ws.on("close", lambda *_: self._logger.info("WebSocket fechado: %s", url))

    def _on_frame(self, payload, direction: str) -> None:
        # 1. Notifica listeners externos primeiro, com isolamento de
        #    falhas. Cada listener vê o payload bruto. Falhas em
        #    listeners NUNCA afetam o pipeline interno de multiplicadores.
        if self._frame_listeners:
            for listener in tuple(self._frame_listeners):
                try:
                    listener(payload, direction)
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning(
                        "frame listener falhou (isolado): %s", exc
                    )

        # 2. Caminho principal: extrair multiplicadores (caminho antigo).
        try:
            values = extract_from_ws_frame(payload)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Erro ao parsear frame WS: %s", exc)
            return
        if not values:
            return
        self._logger.debug(
            "frame %s: %d multiplicadores extraídos", direction, len(values)
        )
        # Evento síncrono dentro de um callback do Playwright; não podemos
        # await aqui. Bufferizamos e o loop principal faz o flush.
        self._buffer.extend(values)

    async def _flush(self, queue: "asyncio.Queue[CollectorEvent]") -> None:
        async with self._buffer_lock:
            if not self._buffer:
                return
            batch = list(self._buffer)
            self._buffer.clear()
        await self.emit(queue, batch)
