"""Métricas de liquidez do book agregado.

Definições neste contexto:

- **Total staked**: soma das apostas iniciais da rodada.
- **Total paid out**: soma de ``stake * cashout_multiplier`` de quem cashou.
- **Liquidity exhaustion**: razão paid_out/staked. Alto significa que
  o cassino "drenou" grande parte das apostas em pagamentos antes do
  crash; baixo significa que a casa absorveu muito (crash precoce ou
  população majoritariamente travada).
- **Player flow**: variação no número de apostadores entre rodadas
  consecutivas. Útil para detectar entrada ou debandada.

Tudo é agregado. Stakes individuais nunca saem do escopo dos módulos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

from app.player_analytics.events import RoundSnapshot


@dataclass(frozen=True)
class LiquidityMetrics:
    total_staked: Optional[float]
    total_paid_out: Optional[float]
    payout_ratio: Optional[float]            # paid_out / staked, em [0, +inf)
    liquidity_exhaustion: Optional[float]    # 0..100, escala invertida (alto = drenado)
    player_count: int


def compute_liquidity(snapshot: RoundSnapshot) -> LiquidityMetrics:
    """Resumo de liquidez de uma rodada."""
    staked = snapshot.total_staked
    paid = snapshot.total_paid_out

    payout_ratio = None
    exhaustion = None
    if staked is not None and staked > 0 and paid is not None:
        payout_ratio = paid / staked
        # Mapeamento: 0% drenado -> 0; 50% -> 50; 100%+ -> 100 (clamp).
        exhaustion = round(min(100.0, max(0.0, payout_ratio * 100.0)), 2)

    return LiquidityMetrics(
        total_staked=staked,
        total_paid_out=paid,
        payout_ratio=round(payout_ratio, 4) if payout_ratio is not None else None,
        liquidity_exhaustion=exhaustion,
        player_count=snapshot.player_count,
    )


@dataclass(frozen=True)
class PlayerFlow:
    delta: int                  # variação absoluta entre rodadas consecutivas
    relative_delta: float       # delta / count_anterior, ou 0 se anterior=0
    direction: str              # "inflow", "outflow", "stable"


def player_flow(
    previous: RoundSnapshot, current: RoundSnapshot, *, stable_threshold: float = 0.05
) -> PlayerFlow:
    """Fluxo de jogadores entre duas rodadas consecutivas."""
    prev_n = previous.player_count
    curr_n = current.player_count
    delta = curr_n - prev_n
    relative = delta / prev_n if prev_n > 0 else 0.0

    if abs(relative) < stable_threshold:
        direction = "stable"
    elif delta > 0:
        direction = "inflow"
    else:
        direction = "outflow"

    return PlayerFlow(
        delta=delta,
        relative_delta=round(relative, 4),
        direction=direction,
    )


def liquidity_trend(
    snapshots: Sequence[RoundSnapshot], window: int = 20
) -> list[Optional[float]]:
    """Série da liquidity_exhaustion ao longo das últimas ``window`` rodadas.

    Útil para detectar "casa esvaziando" ao longo do tempo. ``None`` em
    posições onde a rodada não tinha dados de stake.
    """
    recent = list(snapshots)[-window:]
    return [compute_liquidity(s).liquidity_exhaustion for s in recent]
