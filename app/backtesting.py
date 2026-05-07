from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestConfig:
    initial_bankroll: float
    stake: float
    cashout_target: float
    stop_loss: float
    stop_gain: float
    max_entries: int
    trigger_n: int = 0


@dataclass
class BacktestResult:
    strategy_name: str
    entries: int
    wins: int
    losses: int
    final_bankroll: float
    profit_loss: float
    max_drawdown: float
    hit_rate: float
    roi: float
    bankroll_curve: list[float]


def _finalize(strategy_name: str, wins: int, losses: int, bankroll_curve: list[float], initial: float, stake: float) -> BacktestResult:
    entries = wins + losses
    final_bankroll = bankroll_curve[-1] if bankroll_curve else initial
    pnl = final_bankroll - initial
    peak = initial
    max_dd = 0.0
    for value in bankroll_curve:
        peak = max(peak, value)
        dd = peak - value
        max_dd = max(max_dd, dd)
    hit_rate = (wins / entries * 100) if entries else 0.0
    invested = entries * stake
    roi = (pnl / invested * 100) if invested > 0 else 0.0
    return BacktestResult(strategy_name, entries, wins, losses, final_bankroll, pnl, max_dd, hit_rate, roi, bankroll_curve)


def _can_continue(bankroll: float, cfg: BacktestConfig, entries: int) -> bool:
    if entries >= cfg.max_entries:
        return False
    if bankroll <= cfg.initial_bankroll - cfg.stop_loss:
        return False
    if bankroll >= cfg.initial_bankroll + cfg.stop_gain:
        return False
    return bankroll >= cfg.stake


def _apply_trade(bankroll: float, multiplier: float, target: float, stake: float) -> tuple[float, bool]:
    if multiplier >= target:
        return bankroll + stake * (target - 1), True
    return bankroll - stake, False


def fixed_entry_strategy(df: pd.DataFrame, cfg: BacktestConfig, strategy_name: str) -> BacktestResult:
    bankroll = cfg.initial_bankroll
    wins = losses = entries = 0
    curve = [bankroll]

    for value in df["multiplier"].tolist():
        if not _can_continue(bankroll, cfg, entries):
            break
        bankroll, win = _apply_trade(bankroll, value, cfg.cashout_target, cfg.stake)
        entries += 1
        wins += int(win)
        losses += int(not win)
        curve.append(bankroll)

    return _finalize(strategy_name, wins, losses, curve, cfg.initial_bankroll, cfg.stake)


def after_n_lows_strategy(df: pd.DataFrame, cfg: BacktestConfig, low_threshold: float, strategy_name: str) -> BacktestResult:
    bankroll = cfg.initial_bankroll
    wins = losses = entries = 0
    curve = [bankroll]
    low_streak = 0

    for value in df["multiplier"].tolist():
        low_streak = low_streak + 1 if value < low_threshold else 0
        if low_streak < cfg.trigger_n:
            continue
        if not _can_continue(bankroll, cfg, entries):
            break

        bankroll, win = _apply_trade(bankroll, value, cfg.cashout_target, cfg.stake)
        entries += 1
        wins += int(win)
        losses += int(not win)
        curve.append(bankroll)
        low_streak = 0

    return _finalize(strategy_name, wins, losses, curve, cfg.initial_bankroll, cfg.stake)


def conservative_strategy(df: pd.DataFrame, cfg: BacktestConfig) -> BacktestResult:
    # Estratégia conservadora: alvo ajustado para menor agressividade.
    conservative_target = min(cfg.cashout_target, 1.5)
    new_cfg = BacktestConfig(
        initial_bankroll=cfg.initial_bankroll,
        stake=cfg.stake,
        cashout_target=conservative_target,
        stop_loss=cfg.stop_loss,
        stop_gain=cfg.stop_gain,
        max_entries=cfg.max_entries,
        trigger_n=cfg.trigger_n,
    )
    return fixed_entry_strategy(df, new_cfg, "conservadora_stop")


def run_all_strategies(df: pd.DataFrame, cfg: BacktestConfig) -> list[BacktestResult]:
    return [
        fixed_entry_strategy(
            df,
            BacktestConfig(**{**cfg.__dict__, "cashout_target": 1.5}),
            "fixa_cashout_1_5x",
        ),
        fixed_entry_strategy(
            df,
            BacktestConfig(**{**cfg.__dict__, "cashout_target": 2.0}),
            "fixa_cashout_2x",
        ),
        after_n_lows_strategy(df, cfg, 1.5, "apos_n_abaixo_1_5x"),
        after_n_lows_strategy(df, cfg, 2.0, "apos_n_abaixo_2x"),
        conservative_strategy(df, cfg),
    ]
