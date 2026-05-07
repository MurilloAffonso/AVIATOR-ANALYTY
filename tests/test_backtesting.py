"""Testes das estratégias de backtesting."""

import pandas as pd

from app.backtesting import (
    BacktestConfig,
    after_n_lows_strategy,
    fixed_entry_strategy,
    run_all_strategies,
)


def _cfg(**overrides) -> BacktestConfig:
    base = dict(
        initial_bankroll=100.0,
        stake=10.0,
        cashout_target=2.0,
        stop_loss=1000.0,
        stop_gain=1000.0,
        max_entries=100,
        trigger_n=2,
    )
    base.update(overrides)
    return BacktestConfig(**base)


def test_fixed_entry_all_wins():
    df = pd.DataFrame({"multiplier": [3.0, 3.0, 3.0]})
    result = fixed_entry_strategy(df, _cfg(), "test")
    assert result.entries == 3
    assert result.wins == 3
    assert result.losses == 0
    # Cada win paga stake * (target - 1) = 10 * 1 = 10. 100 + 30 = 130.
    assert result.final_bankroll == 130.0
    assert result.profit_loss == 30.0
    assert result.hit_rate == 100.0


def test_fixed_entry_all_losses():
    df = pd.DataFrame({"multiplier": [1.5, 1.2, 1.8]})
    result = fixed_entry_strategy(df, _cfg(cashout_target=2.0), "test")
    assert result.wins == 0
    assert result.losses == 3
    assert result.final_bankroll == 70.0
    assert result.profit_loss == -30.0


def test_stop_loss_breaks_loop():
    df = pd.DataFrame({"multiplier": [1.0] * 20})
    cfg = _cfg(stop_loss=30.0)  # Para depois de perder 30.
    result = fixed_entry_strategy(df, cfg, "test")
    # Após 3 losses: bankroll = 70 = (initial - stop_loss). Quarta entrada bloqueada.
    assert result.entries == 3
    assert result.final_bankroll == 70.0


def test_stop_gain_breaks_loop():
    df = pd.DataFrame({"multiplier": [3.0] * 20})
    cfg = _cfg(stop_gain=20.0)
    result = fixed_entry_strategy(df, cfg, "test")
    # Após 2 wins: 120 = initial + stop_gain -> bloqueia 3a entrada.
    assert result.entries == 2
    assert result.final_bankroll == 120.0


def test_max_entries_limit():
    df = pd.DataFrame({"multiplier": [3.0] * 100})
    cfg = _cfg(max_entries=5, stop_gain=10**9)
    result = fixed_entry_strategy(df, cfg, "test")
    assert result.entries == 5


def test_after_n_lows_triggers_correctly():
    # 2 baixos seguidos disparam entrada na 2a (n=2). Após entrada o streak reseta.
    df = pd.DataFrame({"multiplier": [1.1, 1.2, 5.0, 1.1, 1.2, 5.0]})
    cfg = _cfg(trigger_n=2, cashout_target=2.0)
    result = after_n_lows_strategy(df, cfg, low_threshold=1.5, strategy_name="test")
    # Pontos de gatilho: índice 1 (valor 1.2 < 2.0 -> loss) e índice 4 (valor 1.2 -> loss).
    assert result.entries == 2
    assert result.losses == 2


def test_run_all_strategies_returns_five():
    df = pd.DataFrame({"multiplier": [1.5, 2.5, 1.2, 3.0, 1.0, 4.0, 1.1, 2.0]})
    results = run_all_strategies(df, _cfg())
    assert len(results) == 5
    names = {r.strategy_name for r in results}
    assert names == {
        "fixa_cashout_1_5x",
        "fixa_cashout_2x",
        "apos_n_abaixo_1_5x",
        "apos_n_abaixo_2x",
        "conservadora_stop",
    }


def test_drawdown_is_non_negative():
    df = pd.DataFrame({"multiplier": [3.0, 1.0, 3.0, 1.0, 3.0, 1.0]})
    result = fixed_entry_strategy(df, _cfg(), "test")
    assert result.max_drawdown >= 0


def test_empty_history_yields_zero_entries():
    df = pd.DataFrame({"multiplier": []}, dtype=float)
    cfg = _cfg()
    result = fixed_entry_strategy(df, cfg, "test")
    assert result.entries == 0
    assert result.final_bankroll == cfg.initial_bankroll
