from __future__ import annotations
"""CCI 商品通道指数震荡策略"""
import numpy as np
import pandas as pd
from .base_strategy import BaseStrategy


class CciStrategy(BaseStrategy):
    name = "cci"

    @staticmethod
    def execute(df: pd.DataFrame) -> pd.Series:
        typical = (df["high"] + df["low"] + df["close"]) / 3
        sma_tp  = typical.rolling(14).mean()
        mad_tp  = typical.rolling(14).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        cci = (typical - sma_tp) / (0.015 * mad_tp)
        signal = pd.Series(0, index=df.index, dtype=int)
        buy  = (cci <= -100) & (cci.shift(1)  > -100)
        sell = (cci >=  100) & (cci.shift(1)  <  100)
        signal[buy]  = 1
        signal[sell] = -1
        return signal
