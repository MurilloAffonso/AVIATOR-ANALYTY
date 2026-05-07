"""Configuração centralizada de logging para a aplicação.

Substitui o ``logging.basicConfig`` espalhado pelos módulos. Idempotente:
chamar ``configure_logging`` várias vezes não duplica handlers.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configura o logger raiz uma única vez."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(level)
    # Evita handlers duplicados se outro código já configurou.
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
