from __future__ import annotations
"""KDJ 随机指标超买超卖策略"""
import pandas as pd
from .base_strategy import BaseStrategy


class KdjStrategy(BaseStrategy):
    name = "kdj"

    @staticmethod
    def execute(df: pd.DataFrame) -> pd.Series:
        low_n  = df["low"].rolling(9).min()
        high_n = df["high"].rolling(9).max()
        rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, float("nan")) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        signal = pd.Series(0, index=df.index, dtype=int)
        buy  = (k > d) & (k.shift(1) <= d.shift(1)) & (k < 30)
        sell = (k < d) & (k.shift(1) >= d.shift(1)) & (k > 70)
        signal[buy]  = 1
        signal[sell] = -1
        return signal
