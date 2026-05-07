from __future__ import annotations

import pandas as pd


def rolling_volatility(df: pd.DataFrame, window: int = 20) -> pd.Series:
    if df.empty:
        return pd.Series(dtype="float64")
    return df["multiplier"].rolling(window=window).std()
