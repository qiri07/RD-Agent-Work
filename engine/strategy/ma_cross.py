from __future__ import annotations
"""双均线交叉策略"""
import pandas as pd
from .base_strategy import BaseStrategy


class MaCrossStrategy(BaseStrategy):
    name = "ma_cross"

    @staticmethod
    def execute(df: pd.DataFrame) -> pd.Series:
        ma5  = df["close"].rolling(5).mean()
        ma10 = df["close"].rolling(10).mean()
        signal = pd.Series(0, index=df.index, dtype=int)
        buy  = (ma5  > ma10) & (ma5.shift(1)  <= ma10.shift(1))
        sell = (ma5  < ma10) & (ma5.shift(1)  >= ma10.shift(1))
        signal[buy]  = 1
        signal[sell] = -1
        return signal
