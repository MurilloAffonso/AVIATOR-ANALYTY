"""Coletor ao vivo (somente leitura) para a barra de histórico do Aviator.

Mudanças relativas à versão anterior:

- Deduplicação por sequência (``app.collector.dedup``) em vez de por valor,
  o que conserta a perda silenciosa de multiplicadores baixos repetidos.
- Encerramento gracioso quando o usuário fecha o navegador.
- Logging centralizado via ``app.logging_config``.
- Tratamento explícito de erros do Playwright.
- Filtro defensivo: ignora valores fora do intervalo válido (>= 1.0).
"""

from __future__ import annotations

import re
import time

from playwright.sync_api import Error as PlaywrightError, Page, sync_playwright

from app.analyzer import categorize_multiplier
from app.collector.dedup import find_new_items
from app.database import SessionLocal
from app.logging_config import get_logger
from app.models import RoundResult

logger = get_logger(__name__)

# Casa floats como "1.50x", "12,34X" ou "100x".
MULTIPLIER_PATTERN = re.compile(r"(\d+(?:[\.,]\d+)?)\s*x", re.IGNORECASE)

# Tamanho máximo da janela mantida em memória entre polls.
WINDOW_CAP = 50


def _extract_multipliers(text: str) -> list[float]:
    values: list[float] = []
    for raw in MULTIPLIER_PATTERN.findall(text):
        try:
            values.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return values


def _read_visible_page_text(page: Page) -> str:
    body = page.locator("body")
    if body.count() == 0:
        return ""
    return body.inner_text(timeout=2000)


def _persist(values: list[float]) -> int:
    """Salva no banco e devolve quantos foram efetivamente persistidos."""
    if not values:
        return 0

    saved = 0
    with SessionLocal() as session:
        for value in values:
            normalized = round(value, 2)
            if normalized < 1.0:
                # Multiplicadores válidos no Aviator são sempre >= 1.00x.
                logger.warning("Ignorando valor fora do intervalo: %s", value)
                continue
            session.add(
                RoundResult(
                    multiplier=normalized,
                    category=categorize_multiplier(normalized),
                )
            )
            logger.info("Multiplicador salvo: %.2fx", normalized)
            saved += 1
        session.commit()
    return saved


def collect_live_results(
    url: str,
    poll_interval_seconds: float = 2.0,
    max_runtime_seconds: int = 0,
) -> int:
    """Coleta somente leitura de multiplicadores visíveis na página.

    Não executa cliques, aposta, cashout ou qualquer ação financeira.

    A coleta encerra quando:
    - o usuário fecha o navegador, ou
    - ``max_runtime_seconds`` é atingido (se > 0).

    Returns:
        Quantidade total de multiplicadores novos salvos.
    """
    logger.info("Iniciando coletor em modo leitura: %s", url)

    previous_window: list[float] = []
    total_saved = 0
    start = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded")
        except PlaywrightError as exc:
            logger.error("Falha ao abrir a URL: %s", exc)
            browser.close()
            return 0

        logger.info("Página aberta. Faça login manualmente, se necessário.")
        logger.info("Para encerrar a coleta, basta fechar o navegador.")

        while True:
            if max_runtime_seconds > 0 and (time.time() - start) >= max_runtime_seconds:
                logger.info("Tempo máximo atingido. Encerrando coleta.")
                break

            try:
                page_text = _read_visible_page_text(page)
            except PlaywrightError as exc:
                # Navegador foi fechado pelo usuário ou página inacessível.
                logger.info("Navegador encerrado ou inacessível: %s", exc)
                break

            visible = _extract_multipliers(page_text)
            if not visible:
                logger.debug("Nenhum multiplicador visível neste ciclo.")
                time.sleep(poll_interval_seconds)
                continue

            new_items = find_new_items(previous_window, visible)
            if new_items:
                total_saved += _persist(new_items)
            else:
                logger.debug("Nenhum multiplicador novo neste ciclo.")

            previous_window = visible[-WINDOW_CAP:]
            time.sleep(poll_interval_seconds)

        try:
            context.close()
            browser.close()
        except PlaywrightError:
            pass

    logger.info("Coleta finalizada. Novos multiplicadores salvos: %s", total_saved)
    return total_saved
