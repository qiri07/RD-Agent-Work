from __future__ import annotations
"""
策略信号模块 — 多策略投票融合 + 趋势过滤
=========================================
支持 8 个子策略：双均线交叉 / RSI / MACD / 布林带 / CCI / KDJ / ADX / 量价背离
投票阈值默认 2（至少 2 个策略一致才确认信号），可选趋势过滤（价格 vs MA60）。
"""
import numpy as np
import pandas as pd
from loguru import logger

from .strategy.ma_cross import MaCrossStrategy
from .strategy.rsi import RsiStrategy
from .strategy.macd import MacdStrategy
from .strategy.bollinger import BollingerStrategy
from .strategy.cci import CciStrategy
from .strategy.kdj import KdjStrategy
from .strategy.adx import AdxDirectStrategy
from .strategy.volume_divergence import VolumeDivergenceStrategy

# ─── 策略注册 ──────────────────────────────────────────────────────────────────
_STRATEGIES = {
    "ma_cross":          MaCrossStrategy,
    "rsi":               RsiStrategy,
    "macd":              MacdStrategy,
    "bollinger":         BollingerStrategy,
    "cci":               CciStrategy,
    "kdj":               KdjStrategy,
    "adx":               AdxDirectStrategy,
    "volume_divergence": VolumeDivergenceStrategy,
}

_DEFAULT_ACTIVE = list(_STRATEGIES.keys())


# ─── 信号融合 ──────────────────────────────────────────────────────────────────
def fuse_signals(signals: list[pd.Series], threshold: int = 2) -> pd.Series:
    """多策略投票融合，返回 {-1, 0, 1} Series"""
    if not signals:
        return pd.Series(dtype=int)
    arr = np.stack([s.values for s in signals])
    buy_score  = np.sum(arr == 1, axis=0)
    sell_score = np.sum(arr == -1, axis=0)
    result = np.where(buy_score  >= threshold,  1,
             np.where(sell_score >= threshold, -1,  0))
    return pd.Series(result, index=signals[0].index)


def apply_trend_filter(df: pd.DataFrame, signal: pd.Series, ma_window: int = 60) -> pd.Series:
    """价格 > MA 时取消卖出，价格 ≤ MA 时取消买入"""
    if "MA60" not in df.columns:
        df = df.copy()
        df["MA60"] = df["close"].rolling(ma_window).mean()
    filtered = signal.copy()
    uptrend  = df["close"] > df["MA60"]
    downtrend = df["close"] <= df["MA60"]
    filtered[uptrend  & (signal == -1)] = 0
    filtered[downtrend & (signal ==  1)] = 0
    return filtered


# ─── 入口函数 ──────────────────────────────────────────────────────────────────
def run_signal_pipeline(
    df: pd.DataFrame,
    active: list[str] | None = None,
    threshold: int = 2,
    trend_filter: bool = True,
    trend_ma_window: int = 60,
) -> dict:
    """
    运行多策略信号生成流水线。

    Args:
        df: 含 OHLCV 列的价格 DataFrame（index 为 datetime）
        active: 启用的策略名列表，None 使用全部 8 个
        threshold: 投票阈值
        trend_filter: 是否启用趋势过滤
        trend_ma_window: 趋势均线窗口

    Returns:
        dict: {signal, strategy_signals, buy_count, sell_count, hold_count}
    """
    active = active or _DEFAULT_ACTIVE
    strategy_signals: dict[str, pd.Series] = {}

    for name in active:
        cls = _STRATEGIES.get(name)
        if cls is None:
            logger.warning("未知策略: %s，跳过", name)
            continue
        try:
            sig = cls.execute(df)
            n_sig = int((sig != 0).sum())
            logger.info("策略 %s → 信号数 %d（买 %d / 卖 %d）",
                        name, n_sig, int((sig == 1).sum()), int((sig == -1).sum()))
            strategy_signals[name] = sig
        except Exception as e:
            logger.warning("策略 %s 执行异常: %s", name, e)

    if not strategy_signals:
        raise RuntimeError("没有策略产生有效信号")

    series = list(strategy_signals.values())
    fused = fuse_signals(series, threshold=threshold)
    logger.info("投票融合完成，买入 %d / 卖出 %d / 持有 %d 日",
                int((fused == 1).sum()), int((fused == -1).sum()),
                int((fused == 0).sum()))

    if trend_filter:
        fused = apply_trend_filter(df, fused, ma_window=trend_ma_window)
        logger.info("趋势过滤后，买入 %d / 卖出 %d / 持有 %d 日",
                    int((fused == 1).sum()), int((fused == -1).sum()),
                    int((fused == 0).sum()))

    return {
        "signal":           fused,
        "strategy_signals": strategy_signals,
        "buy_count":        int((fused == 1).sum()),
        "sell_count":       int((fused == -1).sum()),
        "hold_count":       int((fused == 0).sum()),
    }
