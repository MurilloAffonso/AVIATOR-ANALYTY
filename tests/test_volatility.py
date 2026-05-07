"""Testes do módulo de volatilidade móvel."""

import math

import pandas as pd

from app.volatility import rolling_volatility


def test_empty_dataframe_returns_empty_series():
    df = pd.DataFrame({"multiplier": []}, dtype=float)
    result = rolling_volatility(df)
    assert result.empty
    assert result.dtype == "float64"


def test_first_window_minus_one_values_are_nan():
    """rolling().std() devolve NaN até completar a janela."""
    df = pd.DataFrame({"multiplier": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = rolling_volatility(df, window=3)
    assert math.isnan(result.iloc[0])
    assert math.isnan(result.iloc[1])
    assert not math.isnan(result.iloc[2])


def test_constant_series_has_zero_volatility():
    df = pd.DataFrame({"multiplier": [2.5] * 10})
    result = rolling_volatility(df, window=5)
    # Posições válidas (>= window-1) devem ser todas zero.
    valid_values = result.iloc[4:].tolist()
    assert all(v == 0.0 for v in valid_values)


def test_known_window_matches_pandas_std():
    df = pd.DataFrame({"multiplier": [1.0, 2.0, 3.0]})
    result = rolling_volatility(df, window=3)
    expected = pd.Series([1.0, 2.0, 3.0]).std()  # std amostral padrão do pandas
    assert math.isclose(result.iloc[2], expected, rel_tol=1e-9)


def test_default_window_is_20():
    df = pd.DataFrame({"multiplier": list(range(25))})
    result = rolling_volatility(df)
    # Posições 0..18 são NaN (janela default = 20). 19 em diante são números.
    assert math.isnan(result.iloc[18])
    assert not math.isnan(result.iloc[19])
