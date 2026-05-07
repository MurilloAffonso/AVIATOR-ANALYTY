"""Coletor que lê multiplicadores do DOM via Playwright (somente leitura).

Sucessor da função ``collect_live_results`` antiga. Usa a API assíncrona
do Playwright para integrar bem com :class:`CollectorManager`.

Garantias:
- Apenas operações de leitura (``page.goto``, ``locator.inner_text``).
- Nenhuma chamada a ``click``, ``fill``, ``press``, ``type``, ``hover``,
  ``dispatch_event``, ``select_option``, etc.
- Nenhum frame WebSocket é enviado.
- Encerra graciosamente quando o navegador é fechado pelo usuário.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.collector.base import BaseCollector, CollectorEvent
from app.collector.parser import extract_from_text

# Tamanho máximo da janela mantida em memória entre polls.
WINDOW_CAP = 50


class DOMCollector(BaseCollector):
    """Lê o texto da página em ciclos de polling e extrai multiplicadores.

    Args:
        url: URL do Aviator (cassino).
        poll_interval_seconds: Espera entre leituras consecutivas.
        max_runtime_seconds: Tempo máximo de execução (0 = sem limite).
        headless: Se ``True``, abre o Chromium sem UI. Default ``False``
            para permitir login manual.
    """

    name = "dom"

    def __init__(
        self,
        url: str,
        poll_interval_seconds: float = 2.0,
        max_runtime_seconds: int = 0,
        headless: bool = False,
    ) -> None:
        super().__init__()
        self.url = url
        self.poll_interval_seconds = poll_interval_seconds
        self.max_runtime_seconds = max_runtime_seconds
        self.headless = headless

    async def run_async(self, queue: "asyncio.Queue[CollectorEvent]") -> None:
        # Importação local: Playwright é dependência opcional para testes.
        try:
            from playwright.async_api import (
                Error as PlaywrightError,
                async_playwright,
            )
        except ImportError:
            self._logger.error(
                "Playwright não está instalado. Pule a coleta DOM ou rode "
                "`pip install playwright && playwright install chromium`."
            )
            return

        self._logger.info("Iniciando DOMCollector em modo leitura: %s", self.url)
        previous_window: list[float] = []
        start = time.time()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(self.url, wait_until="domcontentloaded")
            except PlaywrightError as exc:
                self._logger.error("Falha ao abrir a URL: %s", exc)
                await browser.close()
                return

            self._logger.info(
                "Página aberta. Faça login manualmente se necessário."
            )
            self._logger.info(
                "Para encerrar a coleta, basta fechar o navegador."
            )

            while not self.is_stopped:
                if (
                    self.max_runtime_seconds > 0
                    and (time.time() - start) >= self.max_runtime_seconds
                ):
                    self._logger.info(
                        "Tempo máximo atingido. Encerrando DOMCollector."
                    )
                    break

                page_text = await self._safe_read_text(page)
                if page_text is None:
                    # Navegador foi fechado ou página inacessível.
                    break

                visible = extract_from_text(page_text)
                if visible:
                    new_items = _diff_window(previous_window, visible)
                    if new_items:
                        await self.emit(queue, new_items)
                    previous_window = visible[-WINDOW_CAP:]

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass  # Comportamento normal: ciclo de polling.

            try:
                await context.close()
                await browser.close()
            except Exception:  # noqa: BLE001
                pass

        self._logger.info("DOMCollector finalizado.")

    async def _safe_read_text(self, page) -> Optional[str]:
        try:
            from playwright.async_api import Error as PlaywrightError
        except ImportError:
            return None

        try:
            body = page.locator("body")
            if await body.count() == 0:
                return ""
            return await body.inner_text(timeout=2000)
        except PlaywrightError as exc:
            self._logger.info("Navegador encerrado ou inacessível: %s", exc)
            return None


def _diff_window(previous: list[float], current: list[float]) -> list[float]:
    """Wrapper local para evitar import circular em testes que monkeypatch.

    Delega ao módulo ``dedup`` para a lógica real.
    """
    from app.collector.dedup import find_new_items

    return find_new_items(previous, current)
