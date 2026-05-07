"""Curva de sobrevivência por multiplicador.

Para cada rodada (ou agregando várias), calcula:

    S(m) = fração de jogadores que ainda *não* fez cashout quando o
           multiplicador chegou a m

Quem foi pego pelo crash (não cashou) é tratado como **censurado à
direita**: contribui para `S(m)` em todo `m <= crash_multiplier` e some
da população em risco a partir daí. É o estimador de Kaplan-Meier
adaptado: o "evento de saída" aqui é o cashout voluntário; a censura é
o crash.

Saída padrão: lista de pontos ``(m, S(m))`` em ordem crescente de `m`,
útil para plotar diretamente no Streamlit/Plotly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.player_analytics.events import RoundSnapshot


@dataclass(frozen=True)
class SurvivalPoint:
    multiplier: float
    survival: float       # S(m) ∈ [0, 1]
    n_at_risk: int        # jogadores ainda na rodada nesse ponto
    n_events: int         # cashouts ocorridos exatamente em m


def survival_curve_for_round(snapshot: RoundSnapshot) -> list[SurvivalPoint]:
    """Curva de uma única rodada.

    Considera a cauda de não-cashouts como censurada no
    ``crash_multiplier``: eles permanecem em "at risk" até o crash e
    saem sem evento de cashout.
    """
    if snapshot.player_count == 0:
        return []

    cashouts = sorted(snapshot.cashout_multipliers)
    crash = snapshot.crash_multiplier
    crashed = snapshot.players_alive_at_crash

    points: list[SurvivalPoint] = [
        SurvivalPoint(multiplier=1.0, survival=1.0,
                      n_at_risk=snapshot.player_count, n_events=0)
    ]

    n_at_risk = snapshot.player_count
    survival = 1.0

    # Agrupa cashouts por valor (vários jogadores podem cashar no mesmo m).
    grouped: dict[float, int] = {}
    for m in cashouts:
        grouped[m] = grouped.get(m, 0) + 1

    for m in sorted(grouped):
        n_events = grouped[m]
        if n_at_risk <= 0:
            break
        # Kaplan-Meier: S(m) = S(m_prev) * (1 - d/n)
        survival *= max(0.0, 1.0 - n_events / n_at_risk)
        n_at_risk -= n_events
        points.append(SurvivalPoint(m, survival, n_at_risk, n_events))

    # Censura: jogadores que crasharam saem em crash_multiplier sem evento.
    if crashed > 0 and n_at_risk > 0:
        points.append(SurvivalPoint(crash, survival, n_at_risk - crashed, 0))

    return points


def aggregate_survival_curve(
    snapshots: Iterable[RoundSnapshot],
    *,
    grid_step: float = 0.1,
    grid_max: float = 10.0,
) -> list[SurvivalPoint]:
    """Curva agregada: média ponderada por população de cada rodada.

    Usa uma grade fixa em [1.0, ``grid_max``] com passo ``grid_step``.
    Para cada ponto da grade, soma "ainda em risco" e "população inicial"
    de todas as rodadas e devolve a razão.

    Isso é mais robusto que tirar a média das curvas individuais —
    rodadas com muitos jogadores pesam mais, como deveriam.
    """
    snaps = [s for s in snapshots if s.player_count > 0]
    if not snaps:
        return []

    grid: list[float] = []
    m = 1.0
    while m <= grid_max + 1e-9:
        grid.append(round(m, 4))
        m += grid_step

    points: list[SurvivalPoint] = []
    for grid_m in grid:
        total_initial = 0
        total_alive = 0
        for s in snaps:
            total_initial += s.player_count
            # Quantos ainda estavam vivos quando o multiplicador chegou em grid_m?
            alive = _alive_at(s, grid_m)
            total_alive += alive
        if total_initial == 0:
            continue
        survival = total_alive / total_initial
        points.append(SurvivalPoint(grid_m, survival, total_alive, 0))

    return points


def _alive_at(snapshot: RoundSnapshot, m: float) -> int:
    """Quantos jogadores ainda não cashearam quando o multiplicador era m,
    *condicionado* a a rodada ainda estar viva (m <= crash_multiplier)."""
    if m > snapshot.crash_multiplier:
        return 0
    cashed_before_or_at = sum(1 for c in snapshot.cashout_multipliers if c <= m)
    return snapshot.player_count - cashed_before_or_at
