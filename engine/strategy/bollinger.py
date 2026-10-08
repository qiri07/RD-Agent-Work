from __future__ import annotations
"""布林带突破策略"""
import pandas as pd
from .base_strategy import BaseStrategy


class BollingerStrategy(BaseStrategy):
    name = "bollinger"

    @staticmethod
    def execute(df: pd.DataFrame) -> pd.Series:
        mid = df["close"].rolling(20).mean()
        std = df["close"].rolling(20).std()
        upper = mid + 2 * std
        lower = mid - 2 * std
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[df["close"] < lower] = 1
        signal[df["close"] > upper] = -1
        return signal
