"""Distribuição emocional dos cashouts (psicologia agregada da multidão).

Tudo aqui são *bins* sobre cashouts agregados. Nada toca em jogador
individual. As "categorias emocionais" são rótulos heurísticos usados
apenas para visualização; não são diagnóstico psicológico.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.player_analytics.events import RoundSnapshot


# Bins de categorização emocional sobre o multiplicador de cashout.
# São rótulos para *visualização agregada*, não diagnóstico individual.
EMOTION_BINS: tuple[tuple[str, float, float], ...] = (
    ("medo",        1.00, 1.30),
    ("cautela",     1.30, 1.80),
    ("equilibrio",  1.80, 3.00),
    ("ambicao",     3.00, 8.00),
    ("euforia",     8.00, float("inf")),
)


@dataclass(frozen=True)
class EmotionDistribution:
    """Contagens por categoria emocional, mais a fração de "perda"
    (jogadores travados que crasharam, sem cashout)."""

    by_category: dict[str, int]
    crashed: int  # quantos travaram até o crash (sem cashout) — categoria "queimou"
    total_players: int

    def fractions(self) -> dict[str, float]:
        """Fração de cada categoria sobre ``total_players`` (inclui ``queimou``)."""
        if self.total_players == 0:
            return {}
        out = {k: v / self.total_players for k, v in self.by_category.items()}
        out["queimou"] = self.crashed / self.total_players
        return out


def emotion_distribution(snapshot: RoundSnapshot) -> EmotionDistribution:
    """Categoriza os cashouts da rodada por bin emocional."""
    counts = {label: 0 for label, _, _ in EMOTION_BINS}
    for m in snapshot.cashout_multipliers:
        for label, lo, hi in EMOTION_BINS:
            if lo <= m < hi:
                counts[label] += 1
                break
    return EmotionDistribution(
        by_category=counts,
        crashed=snapshot.players_alive_at_crash,
        total_players=snapshot.player_count,
    )


@dataclass(frozen=True)
class HeatmapCell:
    multiplier_bin: str           # rótulo da faixa, ex.: "1.00–1.20"
    multiplier_lo: float
    multiplier_hi: float
    count: int                    # cashouts na faixa, somando todas as rodadas


def exit_heatmap(
    snapshots: Iterable[RoundSnapshot],
    *,
    bin_width: float = 0.20,
    max_multiplier: float = 10.0,
) -> list[HeatmapCell]:
    """Heatmap unidimensional: contagem de cashouts por faixa de multiplicador.

    Não-cashouts (quem crashou) ficam fora do heatmap por construção.
    """
    edges = _build_edges(1.0, max_multiplier, bin_width)
    counts = [0] * (len(edges) - 1)

    for s in snapshots:
        for m in s.cashout_multipliers:
            if m < edges[0]:
                continue
            if m >= edges[-1]:
                counts[-1] += 1
                continue
            idx = int((m - edges[0]) / bin_width)
            idx = min(idx, len(counts) - 1)
            counts[idx] += 1

    return [
        HeatmapCell(
            multiplier_bin=f"{edges[i]:.2f}–{edges[i + 1]:.2f}",
            multiplier_lo=edges[i],
            multiplier_hi=edges[i + 1],
            count=counts[i],
        )
        for i in range(len(counts))
    ]


def _build_edges(lo: float, hi: float, width: float) -> list[float]:
    edges = [lo]
    cur = lo
    while cur < hi:
        cur = round(cur + width, 4)
        edges.append(cur)
    return edges
