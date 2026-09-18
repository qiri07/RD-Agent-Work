#!/usr/bin/env python3
from __future__ import annotations
"""
IC 计算模块
===========
计算单点和时间序列 Spearman IC。
"""
import logging
from typing import Dict, Optional
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logger = logging.getLogger(__name__)


def compute_single_ic(factor: pd.Series, returns: pd.Series) -> float:
    """计算单个时间点的 Spearman IC"""
    common_idx = factor.dropna().index.intersection(returns.dropna().index)
    if len(common_idx) < 100:
        return np.nan

    f = factor.loc[common_idx]
    r = returns.loc[common_idx]

    ic, _ = spearmanr(f, r)
    return ic if np.isfinite(ic) else np.nan


def compute_ic_time_series(factor: pd.Series, returns: pd.Series) -> Dict[pd.Timestamp, float]:
    """计算时间序列 IC（每日横截面 Spearman 相关）"""
    common_idx = factor.dropna().index.intersection(returns.dropna().index)
    if len(common_idx) < 100:
        return {}

    f = factor.loc[common_idx]
    r = returns.loc[common_idx]

    ic_by_date = {}
    for date in f.index.get_level_values('datetime').unique():
        day_f = f.xs(date, level='datetime')
        day_r = r.xs(date, level='datetime')
        common_stocks = day_f.dropna().index.intersection(day_r.dropna().index)
        if len(common_stocks) < 50:
            continue
        ic, _ = spearmanr(day_f[common_stocks], day_r[common_stocks])
        if np.isfinite(ic):
            ic_by_date[date] = ic

    return ic_by_date
