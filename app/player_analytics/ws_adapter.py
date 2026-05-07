"""Adapter: frames WebSocket -> eventos de domínio do Player Analytics.

Heurísticas conservadoras: só emite eventos quando o payload tem
estrutura claramente reconhecível. Quando o cassino usa nomes de campo
diferentes, dois caminhos:

1. configure ``AVIATOR_PARSER_KEYS`` (já existente) e
   ``AVIATOR_PA_FIELD_MAP`` (novo) para mapear campos por nome;
2. desligue o pipeline e use só o coletor de multiplicador.

O adapter NÃO inventa dados. Sem campos reconhecíveis, devolve ``[]``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from app.player_analytics.events import EventKind, PlayerEvent, RoundEvent


# Campos típicos. Podem ser estendidos via env var
# ``AVIATOR_PA_FIELD_MAP="round_id=roundId,bet=betAmount"``.
_DEFAULT_FIELD_MAP = {
    "round_id": ["round_id", "roundId", "round", "gameId", "game_id"],
    "player_id": ["player_id", "playerId", "user_id", "userId", "uid"],
    "stake": ["stake", "amount", "bet", "betAmount", "wager"],
    "cashout": ["cashout", "cashoutMultiplier", "cashout_x", "exit_x", "x"],
    "payout": ["payout", "win", "winAmount", "won"],
    "crash": ["crash", "crash_point", "crashPoint", "crash_multiplier"],
    "event_type": ["type", "event", "kind", "action"],
}


def _load_field_map() -> dict[str, list[str]]:
    extra = os.environ.get("AVIATOR_PA_FIELD_MAP", "")
    if not extra.strip():
        return _DEFAULT_FIELD_MAP
    out = {k: list(v) for k, v in _DEFAULT_FIELD_MAP.items()}
    for pair in extra.split(","):
        if "=" not in pair:
            continue
        canonical, raw = pair.split("=", 1)
        canonical = canonical.strip()
        raw = raw.strip()
        if canonical in out and raw:
            out[canonical] = [raw, *out[canonical]]
    return out


def parse_ws_frame_for_events(payload: str | bytes) -> list[object]:
    """Converte um frame WS num conjunto de eventos de domínio.

    Retorna lista vazia se o frame não tem estrutura reconhecível.
    Aceita tanto eventos isolados quanto arrays de eventos.
    """
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return []
    if not payload:
        return []

    stripped = payload.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return []
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return []

    field_map = _load_field_map()
    events: list[object] = []

    if isinstance(decoded, list):
        for item in decoded:
            events.extend(_extract_events_from_dict(item, field_map))
    elif isinstance(decoded, dict):
        events.extend(_extract_events_from_dict(decoded, field_map))

    return events


def _extract_events_from_dict(node: Any, field_map: dict[str, list[str]]) -> list[object]:
    if not isinstance(node, dict):
        return []

    # Algumas APIs aninham o evento sob "data" / "payload" / "msg".
    for wrapper in ("data", "payload", "msg", "body"):
        if wrapper in node and isinstance(node[wrapper], dict):
            inner = _extract_events_from_dict(node[wrapper], field_map)
            if inner:
                return inner

    event_type = _first_value(node, field_map["event_type"])
    round_id = _first_value(node, field_map["round_id"])

    # Sem round_id é impossível atribuir o evento a uma rodada.
    if round_id is None:
        return []
    round_id = str(round_id)

    out: list[object] = []

    # Crash
    crash = _first_value(node, field_map["crash"])
    if crash is not None and _is_number(crash):
        out.append(
            RoundEvent(
                kind=EventKind.ROUND_CRASH,
                round_id=round_id,
                crash_multiplier=round(float(crash), 2),
            )
        )

    # Bet placed
    stake = _first_value(node, field_map["stake"])
    if (
        stake is not None
        and _is_number(stake)
        and (event_type is None or _looks_like(event_type, ("bet", "place", "stake")))
    ):
        anon = _anonymize(_first_value(node, field_map["player_id"]))
        if anon is not None:
            out.append(
                PlayerEvent(
                    kind=EventKind.BET_PLACED,
                    round_id=round_id,
                    anon_id=anon,
                    stake=float(stake),
                )
            )

    # Cashout
    cashout = _first_value(node, field_map["cashout"])
    if cashout is not None and _is_number(cashout):
        anon = _anonymize(_first_value(node, field_map["player_id"]))
        if anon is not None:
            payout = _first_value(node, field_map["payout"])
            payout_val = float(payout) if _is_number(payout) else None
            out.append(
                PlayerEvent(
                    kind=EventKind.CASHOUT,
                    round_id=round_id,
                    anon_id=anon,
                    cashout_multiplier=float(cashout),
                    payout=payout_val,
                )
            )

    return out


# ---------- helpers ----------

def _first_value(node: dict, candidates: list[str]) -> Any:
    for key in candidates:
        if key in node:
            return node[key]
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _looks_like(value: Any, hints: tuple[str, ...]) -> bool:
    if not isinstance(value, str):
        return False
    low = value.lower()
    return any(h in low for h in hints)


def _anonymize(raw: Any) -> str | None:
    """Hash opaco do ID do jogador.

    Não é reversível, não persiste, e nem precisa ser estável entre
    sessões — serve apenas para deduplicar dentro de uma rodada.
    """
    if raw is None:
        return None
    s = str(raw).encode("utf-8", errors="ignore")
    if not s:
        return None
    return hashlib.sha256(s).hexdigest()[:16]
