"""Renderização Streamlit do Player Analytics Engine.

Mantida em módulo separado para não inflar ``app/main.py``. Cada função
recebe os dados já carregados (snapshots) e desenha um bloco da UI.
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.player_analytics.crowd_behavior import compute_crowd_metrics
from app.player_analytics.events import RoundSnapshot
from app.player_analytics.liquidity import (
    compute_liquidity,
    liquidity_trend,
    player_flow,
)
from app.player_analytics.psychology import emotion_distribution, exit_heatmap
from app.player_analytics.survival import aggregate_survival_curve
from app.player_analytics.whales import detect_whales


def render_player_analytics(snapshots: Sequence[RoundSnapshot]) -> None:
    """Renderiza o painel completo do Player Analytics.

    Args:
        snapshots: lista de snapshots persistidos, ordem cronológica
            (mais antigo primeiro).
    """
    st.header("Player Analytics")
    st.caption(
        "Painel agregado e anônimo do comportamento coletivo. Nenhum "
        "dado individual de jogador é exibido ou armazenado."
    )

    if not snapshots:
        st.info(
            "Sem snapshots de rodada ainda. Execute a coleta ao vivo para "
            "começar a popular este painel."
        )
        return

    latest = snapshots[-1]

    _render_top_metrics(latest, snapshots)
    st.divider()
    _render_survival_curve(snapshots)
    st.divider()
    _render_emotion_and_heatmap(latest, snapshots)
    st.divider()
    _render_liquidity_and_flow(latest, snapshots)
    st.divider()
    _render_whales(latest, snapshots)


# ---------- Top metrics ----------

def _render_top_metrics(
    latest: RoundSnapshot, snapshots: Sequence[RoundSnapshot]
) -> None:
    st.subheader("Última rodada")
    crowd = compute_crowd_metrics(latest)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Jogadores", latest.player_count)
    c2.metric("Vivos no crash", latest.players_alive_at_crash)
    c3.metric("Cashearam", latest.cashed_out_count)
    c4.metric("Crash", f"{latest.crash_multiplier:.2f}x")

    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Greed Index", f"{crowd.greed_index:.1f}")
    g2.metric("Panic Exit", f"{crowd.panic_exit_score:.1f}")
    g3.metric("Crowd Aggression", f"{crowd.crowd_aggression:.1f}")
    g4.metric(
        "Sobreviventes",
        f"{latest.survival_rate * 100:.1f}%",
    )

    st.caption(
        "Greed Index e Panic Exit são heurísticas estatísticas em escala "
        "0–100, não previsões. Veja a documentação para a definição exata."
    )


# ---------- Survival ----------

def _render_survival_curve(snapshots: Sequence[RoundSnapshot]) -> None:
    st.subheader("Curva de sobrevivência (agregada)")
    curve = aggregate_survival_curve(snapshots, grid_step=0.1, grid_max=10.0)
    if not curve:
        st.info("Sem dados suficientes.")
        return
    df = pd.DataFrame(
        {
            "multiplier": [p.multiplier for p in curve],
            "survival": [p.survival for p in curve],
        }
    )
    fig = px.line(
        df,
        x="multiplier",
        y="survival",
        title="Fração de jogadores ainda expostos por multiplicador",
        labels={"multiplier": "Multiplicador", "survival": "S(m)"},
    )
    fig.update_layout(yaxis=dict(range=[0, 1]))
    st.plotly_chart(fig, use_container_width=True)


# ---------- Emotion + heatmap ----------

def _render_emotion_and_heatmap(
    latest: RoundSnapshot, snapshots: Sequence[RoundSnapshot]
) -> None:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Distribuição emocional (última rodada)")
        dist = emotion_distribution(latest)
        fracs = dist.fractions()
        if fracs:
            df = pd.DataFrame(
                {"categoria": list(fracs.keys()), "fracao": list(fracs.values())}
            )
            order = ["medo", "cautela", "equilibrio", "ambicao", "euforia", "queimou"]
            df["categoria"] = pd.Categorical(df["categoria"], categories=order, ordered=True)
            df = df.sort_values("categoria")
            fig = px.bar(df, x="categoria", y="fracao",
                         labels={"fracao": "Fração de jogadores"})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem cashouts na última rodada.")

    with col2:
        st.subheader("Exit heatmap (todas as rodadas)")
        cells = exit_heatmap(snapshots, bin_width=0.20, max_multiplier=10.0)
        if cells:
            df = pd.DataFrame(
                {
                    "faixa": [c.multiplier_bin for c in cells],
                    "lo": [c.multiplier_lo for c in cells],
                    "count": [c.count for c in cells],
                }
            )
            df = df.sort_values("lo")
            fig = px.bar(df, x="faixa", y="count",
                         labels={"count": "Cashouts"})
            fig.update_xaxes(tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados.")


# ---------- Liquidity + flow ----------

def _render_liquidity_and_flow(
    latest: RoundSnapshot, snapshots: Sequence[RoundSnapshot]
) -> None:
    st.subheader("Liquidez e fluxo de jogadores")
    liq = compute_liquidity(latest)

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Total apostado", f"{liq.total_staked:.2f}" if liq.total_staked else "—"
    )
    c2.metric(
        "Total pago", f"{liq.total_paid_out:.2f}" if liq.total_paid_out else "—"
    )
    c3.metric(
        "Liquidity exhaustion",
        f"{liq.liquidity_exhaustion:.1f}" if liq.liquidity_exhaustion is not None else "—",
        help="100 = casa pagou tudo; 0 = casa absorveu tudo.",
    )

    if len(snapshots) >= 2:
        flow = player_flow(snapshots[-2], snapshots[-1])
        st.write(
            f"**Fluxo:** {flow.direction} "
            f"({flow.delta:+d} jogadores, "
            f"{flow.relative_delta * 100:+.1f}%)"
        )

    trend = liquidity_trend(snapshots, window=30)
    if any(v is not None for v in trend):
        df = pd.DataFrame(
            {"rodada": list(range(1, len(trend) + 1)), "exhaustion": trend}
        )
        fig = px.line(
            df,
            x="rodada",
            y="exhaustion",
            title="Liquidity exhaustion (últimas 30 rodadas)",
        )
        fig.update_layout(yaxis=dict(range=[0, 100]))
        st.plotly_chart(fig, use_container_width=True)


# ---------- Whales ----------

def _render_whales(
    latest: RoundSnapshot, snapshots: Sequence[RoundSnapshot]
) -> None:
    st.subheader("Detecção de whales (estatística, anônima)")
    summary = detect_whales(latest)

    c1, c2, c3 = st.columns(3)
    c1.metric("Whales", summary.whale_count)
    c2.metric("Mega whales", summary.mega_whale_count)
    c3.metric(
        "Volume vindo de whales",
        f"{summary.whale_share_of_volume * 100:.1f}%",
    )
    if summary.median_stake > 0:
        st.caption(
            f"Mediana de stake: {summary.median_stake:.2f}. "
            f"Maior stake observado: {summary.largest_stake:.2f}."
        )
    else:
        st.caption(
            "Cassino não expõe stake nesta integração; whale detection desligada."
        )
