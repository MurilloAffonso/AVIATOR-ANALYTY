"""Parser de multiplicadores do Aviator.

Centraliza toda a lógica de extração de números a partir de fontes
heterogêneas (texto visível na página, payloads JSON de WebSocket).
Mantido isolado para que possa ser exercitado em testes sem dependência
de Playwright ou navegador.

Regras:
- Multiplicador válido no Aviator é sempre ``>= 1.00x``.
- Aceita formatos comuns: ``"1.50x"``, ``"12,34X"``, ``"100x"``, ``1.5``.
- Em payloads JSON, varre recursivamente procurando por chaves típicas
  do domínio (``multiplier``, ``crash_point``, ``coefficient``, etc.) e
  por números que pareçam multiplicadores no texto bruto.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from typing import Any

# Casa floats como "1.50x", "12,34X" ou "100x".
MULTIPLIER_PATTERN = re.compile(r"(\d+(?:[\.,]\d+)?)\s*x", re.IGNORECASE)

# Chaves comuns em payloads de WebSocket de jogos crash-style.
# Pode ser estendido em runtime via env var ``AVIATOR_PARSER_KEYS``
# (lista separada por vírgula). Útil quando um cassino específico
# nomeia o campo de um jeito incomum (ex.: ``finalCoefficient``).
_DEFAULT_KEYS = (
    "multiplier",
    "crash_point",
    "crashPoint",
    "coefficient",
    "result",
    "value",
    "x",
)


def _current_keys() -> frozenset[str]:
    extra = os.environ.get("AVIATOR_PARSER_KEYS", "")
    extras = tuple(k.strip() for k in extra.split(",") if k.strip())
    return frozenset(_DEFAULT_KEYS + extras)


# Snapshot conveniente para introspecção; o parser usa ``_current_keys()``
# internamente para que mudanças de env var em runtime/tests sejam visíveis.
JSON_MULTIPLIER_KEYS = _current_keys()

# Limite superior defensivo. Aviator real raramente passa de 1000x; valores
# acima quase certamente vêm de timestamps, IDs ou ruído numérico do payload.
MAX_PLAUSIBLE_MULTIPLIER = 100_000.0


def extract_from_text(text: str) -> list[float]:
    """Extrai multiplicadores de uma string livre (DOM, log, etc.).

    Devolve apenas valores ``>= 1.0`` e ``<= MAX_PLAUSIBLE_MULTIPLIER``,
    arredondados a duas casas decimais.
    """
    values: list[float] = []
    if not text:
        return values

    for raw in MULTIPLIER_PATTERN.findall(text):
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        if _is_plausible(value):
            values.append(round(value, 2))
    return values


def extract_from_json(payload: Any) -> list[float]:
    """Extrai multiplicadores de um payload já decodificado (dict/list).

    Faz uma busca recursiva por chaves em ``JSON_MULTIPLIER_KEYS``. Se o
    valor associado for um número plausível, é incluído. Não tenta
    "adivinhar" multiplicadores em chaves desconhecidas — preferimos
    silêncio a falsos positivos vindos de IDs ou timestamps.
    """
    found: list[float] = []
    _walk_json(payload, found)
    return found


def extract_from_ws_frame(frame_payload: str | bytes) -> list[float]:
    """Extrai multiplicadores de um frame WebSocket cru.

    Tenta primeiro decodificar como JSON. Se falhar, cai para extração
    via texto. Frames binários não-UTF-8 são ignorados.
    """
    if isinstance(frame_payload, bytes):
        try:
            frame_payload = frame_payload.decode("utf-8")
        except UnicodeDecodeError:
            return []

    if not frame_payload:
        return []

    stripped = frame_payload.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            decoded = json.loads(stripped)
            return extract_from_json(decoded)
        except json.JSONDecodeError:
            pass

    return extract_from_text(frame_payload)


def _walk_json(node: Any, out: list[float]) -> None:
    keys = _current_keys()
    _walk_json_inner(node, out, keys)


def _walk_json_inner(node: Any, out: list[float], keys: frozenset[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and _is_number(value):
                numeric = float(value)
                if _is_plausible(numeric):
                    out.append(round(numeric, 2))
            else:
                _walk_json_inner(value, out, keys)
    elif isinstance(node, list):
        for item in node:
            _walk_json_inner(item, out, keys)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_plausible(value: float) -> bool:
    return 1.0 <= value <= MAX_PLAUSIBLE_MULTIPLIER


def normalize(values: Iterable[float]) -> list[float]:
    """Normaliza uma sequência aplicando os mesmos filtros do parser."""
    return [round(v, 2) for v in values if _is_plausible(v)]
