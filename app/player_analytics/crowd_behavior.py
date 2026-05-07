"""Métricas de comportamento coletivo.

Tudo aqui é derivado de agregados; nenhuma métrica usa identidade
individual de jogador. As escalas (0-100) são heurísticas — são
*indicadores*, não previsões.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from app.player_analytics.events import RoundSnapshot


@dataclass(frozen=True)
class CrowdMetrics:
    """Bundle de métricas de comportamento coletivo para uma rodada."""

    greed_index: float           # 0..100 — quão "ganancioso" foi o cashout mediano
    panic_exit_score: float      # 0..100 — quão concentrado foi o cashout num pico curto
    crowd_aggression: float      # 0..100 — combinação de greed + stake médio relativo
    early_exit_rate: float       # fração de cashouts em < 1.5x
    late_exit_rate: float        # fração de cashouts em >= 5x


# ---------- Greed Index ----------

# Limites usados para mapear "cashout mediano" -> 0..100.
# 1.0x  -> 0   (não jogou / saiu instantâneo)
# 1.5x  -> 25
# 2.0x  -> 50
# 5.0x  -> 80
# >= 10x -> 100
_GREED_ANCHORS = [
    (1.0, 0.0),
    (1.5, 25.0),
    (2.0, 50.0),
    (5.0, 80.0),
    (10.0, 100.0),
]


def greed_index(snapshot: RoundSnapshot) -> float:
    """Mede a "ganância" coletiva pela mediana dos cashouts.

    Mediana é mais robusta que média contra whales que cashoam tarde.
    Retorna 0 se não houve cashouts.
    """
    if not snapshot.cashout_multipliers:
        return 0.0
    med = median(snapshot.cashout_multipliers)
    return _piecewise_linear(med, _GREED_ANCHORS)


# ---------- Panic Exit ----------

def panic_exit_score(
    snapshot: RoundSnapshot,
    *,
    window: float = 0.10,
) -> float:
    """Detecta saídas em massa concentradas num intervalo curto.

    Encontra a janela de largura ``window`` (em multiplicador) com mais
    cashouts. Se essa janela contém >40% dos cashouts e está em
    multiplicador baixo (<2x), pontua alto. Heurística de "todo mundo
    correu para a saída ao mesmo tempo".

    Retorna 0..100.
    """
    cashouts = sorted(snapshot.cashout_multipliers)
    n = len(cashouts)
    if n < 5:  # pouco sinal estatístico
        return 0.0

    best_count = 0
    best_center = 1.0
    # Janela deslizante O(n).
    j = 0
    for i in range(n):
        while j < n and cashouts[j] - cashouts[i] <= window:
            j += 1
        count = j - i
        if count > best_count:
            best_count = count
            best_center = (cashouts[i] + cashouts[j - 1]) / 2

    concentration = best_count / n  # 0..1
    if concentration < 0.40:
        return 0.0

    # Quão "panic" é depende de onde foi o pico:
    # picos em <1.5x são mais sintomáticos de pânico que picos em 3x.
    location_factor = max(0.0, min(1.0, (3.0 - best_center) / 2.0))
    return round(min(100.0, concentration * 100.0 * location_factor), 2)


# ---------- Crowd Aggression ----------

def crowd_aggression(snapshot: RoundSnapshot) -> float:
    """Combina ganância e participação para medir "fome" coletiva.

    Componentes:
    - greed_index (peso 0.6): cashout mediano alto sinaliza apetite por risco;
    - participation_factor (peso 0.4): muitos jogadores na rodada amplificam.

    O `participation_factor` é normalizado contra um limiar suave de 100
    jogadores; rodadas com 1000+ batem teto. Sem stakes (cassino não
    expõe), cai para o componente de ganância apenas.
    """
    g = greed_index(snapshot)
    participation = min(1.0, snapshot.player_count / 100.0)
    score = 0.6 * g + 0.4 * (participation * 100.0)
    return round(min(100.0, score), 2)


# ---------- Exit rates por faixa ----------

def early_exit_rate(snapshot: RoundSnapshot, threshold: float = 1.5) -> float:
    if not snapshot.cashout_multipliers:
        return 0.0
    early = sum(1 for c in snapshot.cashout_multipliers if c < threshold)
    return early / len(snapshot.cashout_multipliers)


def late_exit_rate(snapshot: RoundSnapshot, threshold: float = 5.0) -> float:
    if not snapshot.cashout_multipliers:
        return 0.0
    late = sum(1 for c in snapshot.cashout_multipliers if c >= threshold)
    return late / len(snapshot.cashout_multipliers)


# ---------- Compute all ----------

def compute_crowd_metrics(snapshot: RoundSnapshot) -> CrowdMetrics:
    return CrowdMetrics(
        greed_index=round(greed_index(snapshot), 2),
        panic_exit_score=panic_exit_score(snapshot),
        crowd_aggression=crowd_aggression(snapshot),
        early_exit_rate=round(early_exit_rate(snapshot), 4),
        late_exit_rate=round(late_exit_rate(snapshot), 4),
    )


# ---------- helpers ----------

def _piecewise_linear(x: float, anchors: Sequence[tuple[float, float]]) -> float:
    """Interpolação linear com clamp nas pontas."""
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return anchors[-1][1]
