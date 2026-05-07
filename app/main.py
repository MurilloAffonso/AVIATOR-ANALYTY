from __future__ import annotations

import asyncio

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.analyzer import analyze_advanced, summarize
from app.collector.browser import collect_live_results  # wrapper retrocompat
from app.collector.dom_collector import DOMCollector
from app.collector.manager import CollectorManager
from app.collector.manual import save_manual_multiplier
from app.collector.ws_collector import WebSocketCollector
from app.backtesting import BacktestConfig, run_all_strategies
from app.database import SessionLocal, init_db
from app.models import RoundResult
from app.player_analytics.storage import load_all_snapshots
from app.player_analytics.ui import render_player_analytics


def load_history() -> pd.DataFrame:
    with SessionLocal() as session:
        rows = session.query(RoundResult).order_by(RoundResult.created_at.asc()).all()

    data = [
        {
            "id": row.id,
            "multiplier": row.multiplier,
            "category": row.category,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    return pd.DataFrame(data)


def render_metrics(df: pd.DataFrame) -> None:
    stats = summarize(df)
    c1, c2, c3 = st.columns(3)
    c4, c5, c6 = st.columns(3)

    c1.metric("Total de rodadas", stats.total_rounds)
    c2.metric("Média", f"{stats.avg_multiplier:.2f}x")
    c3.metric("Maior multiplicador", f"{stats.max_multiplier:.2f}x")
    c4.metric("% abaixo de 1.5x", f"{stats.pct_below_1_5:.2f}%")
    c5.metric("% acima de 3x", f"{stats.pct_above_3:.2f}%")
    c6.metric("% acima de 10x", f"{stats.pct_above_10:.2f}%")


def render_charts(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Adicione multiplicadores para visualizar os gráficos.")
        return

    line_df = df.copy()
    line_df["round"] = range(1, len(line_df) + 1)
    line_fig = px.line(line_df, x="round", y="multiplier", title="Evolução dos multiplicadores")
    st.plotly_chart(line_fig, use_container_width=True)

    order = ["baixo", "medio", "alto", "grande", "explosivo"]
    dist_df = df.groupby("category", as_index=False)["id"].count().rename(columns={"id": "count"})
    dist_df["category"] = pd.Categorical(dist_df["category"], categories=order, ordered=True)
    dist_df = dist_df.sort_values("category")

    dist_fig = px.bar(dist_df, x="category", y="count", title="Distribuição por categoria")
    st.plotly_chart(dist_fig, use_container_width=True)



def render_advanced_analysis(df: pd.DataFrame) -> None:
    st.subheader("Análise avançada")
    analysis = analyze_advanced(df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Baixos consecutivos (atual)", analysis.consecutive_lows_current)
    c2.metric("Maior sequência de baixos", analysis.consecutive_lows_max)
    c3.metric("Intervalo médio > 10x", f"{analysis.avg_interval_above_10:.2f} rodadas")
    c4.metric("Intervalo médio > 50x", f"{analysis.avg_interval_above_50:.2f} rodadas")

    v1, v2, v3 = st.columns(3)
    v1.metric("Volatilidade últimas 20", f"{analysis.volatility_20:.3f}")
    v2.metric("Volatilidade últimas 50", f"{analysis.volatility_50:.3f}")
    v3.metric("Volatilidade últimas 100", f"{analysis.volatility_100:.3f}")

    if analysis.low_concentration_alert:
        st.warning("Alerta: concentração anormal de resultados baixos detectada recentemente.")

    if analysis.variance_spike_alert:
        st.warning("Alerta: variância recente subiu de forma relevante frente ao histórico.")

    s1, s2 = st.columns(2)
    s1.metric("Score de risco (0-100)", analysis.risk_score)
    s2.metric("Score de oportunidade estatística (0-100)", analysis.opportunity_score)
    st.caption("Score de oportunidade é apenas estatístico e não representa promessa de previsão.")


def render_backtesting(df: pd.DataFrame) -> None:
    st.subheader("Backtesting (simulação sem aposta real)")
    if df.empty:
        st.info("Adicione histórico para executar backtesting.")
        return

    c1, c2, c3 = st.columns(3)
    c4, c5, c6 = st.columns(3)

    initial_bankroll = c1.number_input("Banca inicial", min_value=1.0, value=1000.0, step=50.0)
    stake = c2.number_input("Valor por entrada", min_value=0.1, value=10.0, step=1.0)
    cashout_target = c3.number_input("Cashout alvo", min_value=1.01, value=2.0, step=0.1)
    stop_loss = c4.number_input("Stop loss", min_value=0.0, value=200.0, step=10.0)
    stop_gain = c5.number_input("Stop gain", min_value=0.0, value=200.0, step=10.0)
    max_entries = int(c6.number_input("Máximo de entradas", min_value=1, value=200, step=10))
    trigger_n = st.number_input("N para entradas após sequência de baixos", min_value=1, value=3, step=1)

    cfg = BacktestConfig(
        initial_bankroll=float(initial_bankroll),
        stake=float(stake),
        cashout_target=float(cashout_target),
        stop_loss=float(stop_loss),
        stop_gain=float(stop_gain),
        max_entries=max_entries,
        trigger_n=int(trigger_n),
    )

    results = run_all_strategies(df, cfg)
    rows = [
        {
            "estrategia": r.strategy_name,
            "entradas": r.entries,
            "acertos": r.wins,
            "erros": r.losses,
            "lucro_prejuizo": round(r.profit_loss, 2),
            "drawdown_max": round(r.max_drawdown, 2),
            "taxa_acerto_%": round(r.hit_rate, 2),
            "roi_%": round(r.roi, 2),
            "banca_final": round(r.final_bankroll, 2),
        }
        for r in results
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    selected = st.selectbox("Estratégia para curva de banca", [r.strategy_name for r in results])
    selected_result = next(r for r in results if r.strategy_name == selected)
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=selected_result.bankroll_curve, mode="lines", name="Banca"))
    fig.update_layout(title=f"Evolução da banca - {selected_result.strategy_name}", xaxis_title="Entradas", yaxis_title="Banca")
    st.plotly_chart(fig, use_container_width=True)

def _run_collectors(
    mode: str,
    url: str,
    poll_seconds: float,
    max_runtime: int,
) -> int:
    """Despacha para a arquitetura nova de coletores conforme o modo escolhido.

    Modo "DOM" preserva o caminho antigo via wrapper síncrono. Os outros
    instanciam o ``CollectorManager`` diretamente.
    """
    if mode == "DOM":
        return collect_live_results(
            url=url,
            poll_interval_seconds=poll_seconds,
            max_runtime_seconds=max_runtime,
        )

    collectors: list = []
    if mode in ("WebSocket", "DOM + WebSocket"):
        collectors.append(
            WebSocketCollector(url=url, max_runtime_seconds=max_runtime)
        )
    if mode == "DOM + WebSocket":
        collectors.append(
            DOMCollector(
                url=url,
                poll_interval_seconds=poll_seconds,
                max_runtime_seconds=max_runtime,
            )
        )

    manager = CollectorManager(collectors)
    return asyncio.run(manager.run())


def main() -> None:
    st.set_page_config(page_title="Aviator Pattern Analyzer", layout="wide")
    st.title("Aviator Pattern Analyzer")
    st.warning(
        "Este painel é apenas analítico. Não há previsão garantida de resultados "
        "e não existe automação de apostas."
    )

    init_db()

    with st.form("new_multiplier_form"):
        value = st.number_input("Novo multiplicador", min_value=1.0, step=0.01, format="%.2f")
        submitted = st.form_submit_button("Salvar")
        if submitted:
            save_manual_multiplier(float(value))
            st.success(f"Multiplicador {value:.2f}x salvo com sucesso.")

    st.subheader("Coleta ao vivo (somente leitura)")
    st.caption(
        "Esta seção apenas observa multiplicadores visíveis na página ou "
        "frames WebSocket recebidos. Nenhum clique, aposta ou cashout é executado."
    )
    aviator_url = st.text_input("URL do Aviator", value="https://example.com/aviator")
    poll_seconds = st.number_input("Intervalo de leitura (segundos)", min_value=1.0, value=2.0, step=0.5)
    max_runtime = st.number_input(
        "Tempo máximo da coleta (segundos, 0 = sem limite)", min_value=0, value=0, step=10
    )
    collector_mode = st.radio(
        "Modo de coleta",
        options=[
            "DOM",
            "WebSocket",
            "DOM + WebSocket",
            "WebSocket + Player Analytics",
        ],
        index=0,
        help=(
            "DOM lê o histórico visível; WebSocket escuta frames recebidos "
            "(menor latência); 'DOM + WebSocket' roda os dois e deduplica; "
            "'WebSocket + Player Analytics' liga a bridge — frames são "
            "enviados ao pipeline analítico em paralelo, sem afetar a "
            "coleta de multiplicadores."
        ),
    )

    if st.button("Iniciar coleta ao vivo"):
        st.info(
            "Será aberto um navegador visível. Faça login manualmente se "
            "necessário. Nenhuma ação de aposta/cashout será executada."
        )
        if collector_mode == "WebSocket + Player Analytics":
            from app.player_analytics.runner import run_sync as run_with_analytics_sync

            result = run_with_analytics_sync(
                url=aviator_url,
                poll_seconds=float(poll_seconds),
                max_runtime=int(max_runtime),
            )
            st.success(
                f"Coleta finalizada. Multiplicadores salvos: "
                f"{result.multipliers_saved}. Snapshots de rodada: "
                f"{result.bridge_metrics.snapshots_generated}."
            )
            with st.expander("Métricas da bridge"):
                st.json(result.bridge_metrics.as_dict())
        else:
            saved = _run_collectors(
                mode=collector_mode,
                url=aviator_url,
                poll_seconds=float(poll_seconds),
                max_runtime=int(max_runtime),
            )
            st.success(f"Coleta finalizada. Novos multiplicadores salvos: {saved}")

    # ---- Replay offline ----
    with st.expander("Replay de sessão WebSocket gravada"):
        st.caption(
            "Carregue um arquivo `.jsonl` (uma linha JSON por frame "
            "recebido) para reprocessar uma sessão sem abrir o navegador. "
            "Útil para validar mudanças de mapeamento de campos contra "
            "dados reais."
        )
        replay_file = st.file_uploader(
            "Arquivo .jsonl", type=["jsonl", "json", "txt"]
        )
        replay_persist = st.checkbox(
            "Persistir snapshots no banco", value=False,
            help="Desligue para apenas ver as métricas sem alterar o histórico.",
        )
        if replay_file is not None and st.button("Executar replay"):
            from app.player_analytics.runner import replay_sync

            raw = replay_file.getvalue().decode("utf-8", errors="ignore")
            payloads = [line for line in raw.splitlines() if line.strip()]
            metrics = replay_sync(payloads, persist=replay_persist)
            st.success(
                f"Replay concluído. Snapshots: "
                f"{metrics.snapshots_generated}. Eventos parseados: "
                f"{metrics.events_parsed}."
            )
            st.json(metrics.as_dict())

    history = load_history()
    st.subheader("Histórico")
    st.dataframe(history, use_container_width=True)

    render_metrics(history)
    render_advanced_analysis(history)
    render_charts(history)
    render_backtesting(history)

    # Player Analytics Engine: depende de snapshots persistidos pelo
    # pipeline de eventos (alimentado por DOM/WS quando o cassino expõe
    # campos de jogador). Se ainda não há snapshots, a seção aparece
    # com uma mensagem explicativa em vez de quebrar.
    snapshots = load_all_snapshots()
    render_player_analytics(snapshots)


if __name__ == "__main__":
    main()
