"""Detecção de "whales" — apostas atípicas em magnitude.

Apenas detecção estatística: identificamos *que existiu* uma aposta
muito acima da distribuição típica da rodada, sem reter quem fez.
Não há perfilamento individual; só presença/ausência e magnitude
relativa. Útil para o operador entender se uma rodada foi anomalamente
"pesada" por causa de poucos jogadores grandes.

Critérios:
- Whale = aposta acima do percentil P95 *e* acima de
  ``threshold_factor * mediana`` da rodada.
- Aposta acima de P99 é classificada como ``mega_whale``.

Sem stakes (cassino não expõe), o módulo simplesmente devolve
``WhaleSummary`` zerado. Não assume e não inventa.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median

from app.player_analytics.events import RoundSnapshot


@dataclass(frozen=True)
class WhaleSummary:
    whale_count: int
    mega_whale_count: int
    whale_share_of_volume: float    # 0..1, fração do total_staked vinda de whales
    largest_stake: float            # 0 se sem dados
    median_stake: float             # 0 se sem dados


def detect_whales(
    snapshot: RoundSnapshot,
    *,
    p95_factor: float = 3.0,
    min_population: int = 10,
) -> WhaleSummary:
    """Identifica whales numa única rodada.

    Args:
        p95_factor: aposta deve ser >= ``factor * mediana`` *além* de
            >= P95 para qualificar.
        min_population: rodadas com poucos jogadores (< 10) não geram
            P95/P99 confiáveis; devolvemos sumário zerado.
    """
    stakes = list(snapshot.stakes)
    if len(stakes) < min_population:
        return _empty()

    stakes_sorted = sorted(stakes)
    med = median(stakes_sorted)
    p95 = _percentile(stakes_sorted, 95)
    p99 = _percentile(stakes_sorted, 99)
    threshold_whale = max(p95, med * p95_factor)
    threshold_mega = max(p99, med * (p95_factor * 2))

    whales = [s for s in stakes_sorted if s >= threshold_whale]
    megas = [s for s in stakes_sorted if s >= threshold_mega]

    total = sum(stakes_sorted)
    whale_share = sum(whales) / total if total > 0 else 0.0

    return WhaleSummary(
        whale_count=len(whales),
        mega_whale_count=len(megas),
        whale_share_of_volume=round(whale_share, 4),
        largest_stake=stakes_sorted[-1],
        median_stake=med,
    )


def whale_presence_trend(
    snapshots: Iterable[RoundSnapshot], window: int = 20
) -> list[int]:
    """Série de ``whale_count`` nas últimas ``window`` rodadas."""
    return [detect_whales(s).whale_count for s in list(snapshots)[-window:]]


# ---------- helpers ----------

def _empty() -> WhaleSummary:
    return WhaleSummary(0, 0, 0.0, 0.0, 0.0)


def _percentile(sorted_values: list[float], p: float) -> float:
    """Percentil tipo "nearest-rank" sobre lista já ordenada.

    Para listas pequenas (n=10), P95 ≈ último elemento; é o suficiente
    para esta aplicação. Não introduzimos numpy só para isso.
    """
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    rank = int(round((p / 100.0) * (n - 1)))
    return sorted_values[max(0, min(n - 1, rank))]
