from __future__ import annotations
"""RSI 超买超卖策略"""
import pandas as pd
from .base_strategy import BaseStrategy


class RsiStrategy(BaseStrategy):
    name = "rsi"

    @staticmethod
    def execute(df: pd.DataFrame) -> pd.Series:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi = 100 - (100 / (1 + rs))
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[rsi < 30] = 1       # 超卖区买入
        signal[rsi > 70] = -1      # 超买区卖出
        return signal
