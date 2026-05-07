"""Wrapper de retrocompatibilidade.

A arquitetura nova vive em :mod:`app.collector.dom_collector`,
:mod:`app.collector.ws_collector` e :mod:`app.collector.manager`. Este
módulo continua expondo a função ``collect_live_results`` que o
``app/main.py`` (Streamlit) usa, agora implementada como um wrapper
síncrono em volta da pipeline assíncrona.

Ainda *somente leitura*: o wrapper apenas instancia um ``DOMCollector``
e o ``CollectorManager``, ambos com proibições explícitas (e testadas)
contra qualquer ação financeira.

``SessionLocal`` é re-exportado para preservar compat com o
``conftest.py`` antigo, que monkey-patcha esse símbolo.
"""

from __future__ import annotations

import asyncio

from app.collector.dom_collector import DOMCollector
from app.collector.manager import CollectorManager
from app.database import SessionLocal  # noqa: F401  (re-exportado p/ tests)
from app.logging_config import get_logger

logger = get_logger(__name__)


def collect_live_results(
    url: str,
    poll_interval_seconds: float = 2.0,
    max_runtime_seconds: int = 0,
    headless: bool = False,
) -> int:
    """Coleta síncrona via DOMCollector + CollectorManager.

    Mantida para o ``app/main.py`` (Streamlit) e para usuários que ainda
    chamam a API antiga. Internamente sobe um event loop e roda a
    arquitetura nova.

    Returns:
        Total de multiplicadores efetivamente persistidos.
    """
    collector = DOMCollector(
        url=url,
        poll_interval_seconds=poll_interval_seconds,
        max_runtime_seconds=max_runtime_seconds,
        headless=headless,
    )
    manager = CollectorManager([collector])

    try:
        return asyncio.run(manager.run())
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário (KeyboardInterrupt).")
        return manager.total_saved
