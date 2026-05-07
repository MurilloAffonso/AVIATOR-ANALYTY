from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable

from playwright.sync_api import Page, sync_playwright

from app.analyzer import categorize_multiplier
from app.database import SessionLocal
from app.models import RoundResult

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

MULTIPLIER_PATTERN = re.compile(r"(\d+(?:[\.,]\d+)?)\s*x", re.IGNORECASE)


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


def _existing_recent_values(limit: int = 500) -> set[float]:
    with SessionLocal() as session:
        rows: Iterable[RoundResult] = (
            session.query(RoundResult)
            .order_by(RoundResult.created_at.desc())
            .limit(limit)
            .all()
        )
        return {round(row.multiplier, 2) for row in rows}


def _save_new_values(values: list[float], known_values: set[float]) -> int:
    new_count = 0
    with SessionLocal() as session:
        for value in values:
            normalized = round(value, 2)
            if normalized in known_values:
                continue
            result = RoundResult(multiplier=normalized, category=categorize_multiplier(normalized))
            session.add(result)
            known_values.add(normalized)
            new_count += 1
            logger.info("Multiplicador salvo: %.2fx (%s)", normalized, result.category)
        session.commit()
    return new_count


def collect_live_results(
    url: str,
    poll_interval_seconds: float = 2.0,
    max_runtime_seconds: int = 0,
) -> int:
    """Coleta somente leitura de multiplicadores visíveis na página.

    Não executa cliques, aposta, cashout ou qualquer ação financeira.
    """
    known_values = _existing_recent_values()
    logger.info("Iniciando coletor em modo leitura: %s", url)
    logger.info("Valores já conhecidos no banco (janela recente): %s", len(known_values))

    total_saved = 0
    start = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        logger.info("Página aberta. Faça login manualmente, se necessário.")
        logger.info("Coletando texto visível para detectar multiplicadores com padrão 'Nx'.")

        while True:
            if max_runtime_seconds > 0 and (time.time() - start) >= max_runtime_seconds:
                logger.info("Tempo máximo de execução atingido. Encerrando coleta.")
                break

            page_text = _read_visible_page_text(page)
            parsed_values = _extract_multipliers(page_text)
            if parsed_values:
                new_items = _save_new_values(parsed_values, known_values)
                total_saved += new_items
                if new_items == 0:
                    logger.info("Nenhum multiplicador novo detectado neste ciclo.")
            else:
                logger.info("Nenhum multiplicador detectado no texto visível neste ciclo.")

            time.sleep(poll_interval_seconds)

        context.close()
        browser.close()

    logger.info("Coleta finalizada. Total de novos multiplicadores salvos: %s", total_saved)
    return total_saved
