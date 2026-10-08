from __future__ import annotations
"""ADX 平均趋向强度策略（直接计算版，不依赖预计算的 ATR 列）"""
import pandas as pd
from .base_strategy import BaseStrategy


class AdxDirectStrategy(BaseStrategy):
    name = "adx"

    @staticmethod
    def execute(df: pd.DataFrame) -> pd.Series:
        # 计算 ATR（若未预计算）
        if "ATR" in df.columns:
            atr = df["ATR"]
        else:
            tr1 = df["high"] - df["low"]
            tr2 = (df["high"] - df["close"].shift()).abs()
            tr3 = (df["low"]  - df["close"].shift()).abs()
            atr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

        plus_dm = df["high"].diff().where(
            (df["high"].diff() > -df["low"].diff()) & (df["high"].diff() > 0), 0)
        minus_dm = (-df["low"].diff()).where(
            (-df["low"].diff() > df["high"].diff()) & (-df["low"].diff() > 0), 0)

        plus_di  = 100 * (plus_dm.rolling(14).mean()  / atr)
        minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
        dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = dx.rolling(14).mean()

        signal = pd.Series(0, index=df.index, dtype=int)
        buy  = (plus_di  > minus_di) & (plus_di.shift(1)  <= minus_di.shift(1)) & (adx > 20)
        sell = (minus_di > plus_di)  & (minus_di.shift(1)  <= plus_di.shift(1))  & (adx > 20)
        signal[buy]  = 1
        signal[sell] = -1
        return signal
