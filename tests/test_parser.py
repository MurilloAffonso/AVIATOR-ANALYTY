"""Testes do parser de multiplicadores.

Cobre extração a partir de:
- texto livre (DOM);
- payloads JSON aninhados (WebSocket);
- frames WS crus (string e bytes);
- valores fora do intervalo plausível.
"""

from __future__ import annotations

import json

from app.collector.parser import (
    extract_from_json,
    extract_from_text,
    extract_from_ws_frame,
    normalize,
)


# ---------- extract_from_text ----------

def test_text_simple_decimal():
    assert extract_from_text("1.50x") == [1.50]


def test_text_with_comma_decimal():
    assert extract_from_text("12,34X") == [12.34]


def test_text_multiple_values_in_order():
    text = "Histórico: 1.50x 2.75x 100x 1.00x"
    assert extract_from_text(text) == [1.5, 2.75, 100.0, 1.0]


def test_text_filters_below_one():
    assert extract_from_text("0.5x 1.2x") == [1.2]


def test_text_empty_returns_empty():
    assert extract_from_text("") == []
    assert extract_from_text(None) == []  # type: ignore[arg-type]


def test_text_filters_implausible_huge_values():
    # Um número absurdo (provavelmente um ID) seguido de "x" não deve passar.
    assert extract_from_text("999999999x 2.5x") == [2.5]


# ---------- extract_from_json ----------

def test_json_flat_multiplier_key():
    assert extract_from_json({"multiplier": 1.75}) == [1.75]


def test_json_camel_case_key():
    assert extract_from_json({"crashPoint": 3.21}) == [3.21]


def test_json_nested_payload():
    payload = {
        "round_id": 42,
        "result": {"coefficient": 2.50, "ts": 1700000000},
    }
    assert extract_from_json(payload) == [2.50]


def test_json_list_of_rounds():
    payload = {
        "history": [
            {"multiplier": 1.10},
            {"multiplier": 5.00},
            {"multiplier": 0.99},  # filtrado: < 1.0
        ]
    }
    assert extract_from_json(payload) == [1.10, 5.00]


def test_json_ignores_unknown_keys():
    """Não inventamos: chaves desconhecidas são ignoradas para evitar
    falsos positivos (IDs, timestamps, etc.)."""
    payload = {"random_id": 1.5, "session_token": 2.3}
    assert extract_from_json(payload) == []


def test_json_boolean_not_treated_as_number():
    # bool é instância de int em Python; o parser deve excluir.
    assert extract_from_json({"multiplier": True}) == []


# ---------- extract_from_ws_frame ----------

def test_ws_frame_json_string():
    frame = json.dumps({"multiplier": 7.25})
    assert extract_from_ws_frame(frame) == [7.25]


def test_ws_frame_json_bytes():
    frame = json.dumps({"multiplier": 4.4}).encode("utf-8")
    assert extract_from_ws_frame(frame) == [4.4]


def test_ws_frame_non_json_falls_back_to_text():
    frame = "evento: round_end multiplier=1.85x"
    assert extract_from_ws_frame(frame) == [1.85]


def test_ws_frame_invalid_bytes_returns_empty():
    assert extract_from_ws_frame(b"\xff\xfe\xfd") == []


def test_ws_frame_empty_returns_empty():
    assert extract_from_ws_frame("") == []
    assert extract_from_ws_frame(b"") == []


def test_ws_frame_array_payload():
    frame = json.dumps([{"multiplier": 1.10}, {"multiplier": 6.00}])
    assert extract_from_ws_frame(frame) == [1.10, 6.00]


# ---------- normalize ----------

def test_normalize_filters_and_rounds():
    assert normalize([0.5, 1.001, 2.999, 1_000_000]) == [1.0, 3.0]


# ---------- AVIATOR_PARSER_KEYS env var ----------

def test_custom_keys_via_env(monkeypatch):
    """Cassinos com nome de campo incomum podem ser suportados via env var."""
    monkeypatch.setenv("AVIATOR_PARSER_KEYS", "finalCoefficient,bet_x")
    payload = {"finalCoefficient": 3.14, "bet_x": 2.0, "ignored": 99.0}
    assert sorted(extract_from_json(payload)) == [2.0, 3.14]


def test_default_keys_still_work_with_extras(monkeypatch):
    """Adicionar chaves não remove as padrões."""
    monkeypatch.setenv("AVIATOR_PARSER_KEYS", "extraKey")
    assert extract_from_json({"multiplier": 1.5}) == [1.5]
    assert extract_from_json({"extraKey": 2.5}) == [2.5]
