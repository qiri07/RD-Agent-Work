from __future__ import annotations
"""MACD 金叉死叉策略"""
import pandas as pd
from .base_strategy import BaseStrategy


class MacdStrategy(BaseStrategy):
    name = "macd"

    @staticmethod
    def execute(df: pd.DataFrame) -> pd.Series:
        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        dif   = ema12 - ema26
        dea   = dif.ewm(span=9).mean()
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[(dif > dif.shift(1)) & (dif.shift(1) <= dea.shift(1))] = 1   # 金叉
        signal[(dif < dif.shift(1)) & (dif.shift(1) >= dea.shift(1))] = -1  # 死叉
        return signal
