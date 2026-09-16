#!/usr/bin/env python3
"""
IC 计算核心模块
===============
Spearman rank IC 计算及常量定义。
"""
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# IC 分析参数
IC_FORWARD_DAYS = [1, 3, 5]   # 向前收益天数
IC_WINSORIZE = 0.01            # 因子值缩尾处理
IC_MIN_STOCKS_PER_DAY = 50     # 每日最少股票数


def compute_ic(factor_df: pd.Series, returns_df: pd.Series,
               forward_days: int = 5) -> float:
    """计算因子与 forward returns 的 IC（rank IC）

    Args:
        factor_df: 因子值序列 (MultiIndex: datetime, instrument)
        returns_df: 收益率序列 (MultiIndex: datetime, instrument)
        forward_days: 向前收益天数

    Returns:
        日度 IC 均值，数据不足返回 nan
    """
    f_dates = factor_df.index.get_level_values(0)
    r_dates = returns_df.index.get_level_values(0)

    common_idx = factor_df.index.intersection(returns_df.index)
    if len(common_idx) < 1000:
        return np.nan

    f = factor_df.loc[common_idx]
    r = returns_df.loc[common_idx]

    daily_ic = pd.Series(index=range(len(f)))
    for dt_val in f_dates.unique():
        mask = f_dates == dt_val
        fg = f[mask]
        rg = r[mask]
        if len(fg) >= IC_MIN_STOCKS_PER_DAY:
            ic_val = fg.corr(rg, method="spearman")
            if not pd.isna(ic_val):
                daily_ic.loc[mask] = ic_val

    daily_ic = daily_ic.dropna()
    if len(daily_ic) < 10:
        return np.nan
    return daily_ic.mean()
