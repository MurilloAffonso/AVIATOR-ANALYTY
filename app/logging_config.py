"""Configuração centralizada de logging para a aplicação.

Suporta dois formatos:

- **Texto** (padrão): legível em terminal, mantém compat com versões
  anteriores.
- **JSON line** (estruturado): habilitado via env var
  ``AVIATOR_LOG_FORMAT=json``. Cada linha é um objeto JSON com
  ``timestamp``, ``level``, ``logger``, ``message`` e — se houver —
  campos extras anexados via ``logger.info("...", extra={"k": v})``.

Idempotente: chamar :func:`configure_logging` mais de uma vez não duplica
handlers.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

_CONFIGURED = False

# Campos padrão do LogRecord que NÃO devem entrar como "extra" no JSON.
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Formata cada registro como uma linha JSON.

    Inclui automaticamente todos os campos extras passados via
    ``logger.x("...", extra={...})``, desde que não colidam com chaves
    reservadas do :class:`logging.LogRecord`.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)  # Garante que é serializável.
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


def _build_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    fmt = os.environ.get("AVIATOR_LOG_FORMAT", "text").lower()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
            )
        )
    return handler


def configure_logging(level: int = logging.INFO) -> None:
    """Configura o logger raiz uma única vez."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(level)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(_build_handler())

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
