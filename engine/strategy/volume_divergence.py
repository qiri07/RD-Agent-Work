from __future__ import annotations
"""量价背离策略"""
import pandas as pd
from .base_strategy import BaseStrategy


class VolumeDivergenceStrategy(BaseStrategy):
    name = "volume_divergence"

    @staticmethod
    def execute(df: pd.DataFrame) -> pd.Series:
        vol_ma5  = df["volume"].rolling(5).mean()
        vol_ma10 = df["volume"].rolling(10).mean()
        vol_ratio = vol_ma5 / vol_ma10.replace(0, float("nan"))

        signal = pd.Series(0, index=df.index, dtype=int)
        # 价格创新低 + 放量 → 做多
        price_new_low  = df["close"] == df["close"].rolling(20).min()
        high_vol = vol_ratio > 1.5
        signal[price_new_low & high_vol] = 1
        # 价格创新高 + 缩量 → 做空
        price_new_high = df["close"] == df["close"].rolling(20).max()
        low_vol  = vol_ratio < 0.5
        signal[price_new_high & low_vol] = -1
        return signal
