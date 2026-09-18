#!/usr/bin/env python3
from __future__ import annotations
"""
统计与IC计算模块（numpy向量化版）
==================================
股票基础统计、Spearman IC计算。
"""
import numpy as np
import pandas as pd
from scipy.stats import t as t_dist


def stock_stats_np(close_arr, dates_arr):
    """向量化统计"""
    n = len(close_arr)
    if n < 200:
        return None
    rets = np.diff(np.log(close_arr))
    nn = len(rets)
    if nn < 100:
        return None

    cum_log = np.cumsum(rets)
    ann_ret = np.exp(cum_log[-1] * 252 / nn) - 1
    ann_vol = np.std(rets, ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cumret = np.exp(cum_log)
    dd = float((cumret / np.maximum.accumulate(cumret) - 1).min())

    # Yearly
    years = None
    yearly = []
    if hasattr(dates_arr, 'dtype') and np.issubdtype(dates_arr.dtype, np.datetime64):
        years = pd.to_datetime(dates_arr).year
    elif hasattr(dates_arr, 'dtype') and np.issubdtype(dates_arr.dtype, np.integer):
        # 测试数据中 dates_arr 可能是整数（ticker代码），无法计算年度统计
        years = None
    else:
        try:
            years = np.array([getattr(d, 'year', None) for d in dates_arr])
            years = years[~pd.isna(years)]
        except Exception:
            years = None
    if years is None or len(years) < 2:
        yearly = []
    else:
        years_ret = years[1:]  # align with rets (n-1)
        for y in np.unique(years_ret):
            mask = years_ret == y
            r = rets[mask]
            if len(r) < 100:
                continue
            ar = np.exp(np.sum(r) * 252 / len(r)) - 1
            vol = np.std(r, ddof=1) * np.sqrt(252)
            cr = np.exp(np.cumsum(r))
            ydd = float((cr / np.maximum.accumulate(cr) - 1).min())
            yearly.append({
                'year': int(y),
                'return_pct': round(ar*100, 2),
                'volatility_pct': round(vol*100, 2),
                'max_drawdown_pct': round(ydd*100, 2),
                'trading_days': len(r),
                'win_rate': round(float((r > 0).mean()*100), 1),
            })

    return {
        'n_days': n,
        'price_min': round(float(close_arr.min()), 2),
        'price_max': round(float(close_arr.max()), 2),
        'ann_return_pct': round(float(ann_ret*100), 2),
        'ann_volatility_pct': round(float(ann_vol*100), 2),
        'sharpe': round(float(sharpe), 2),
        'max_drawdown_pct': round(float(dd*100), 2),
        'yearly': yearly,
    }


def ic_numpy(f_vals, r_vals):
    """Spearman IC"""
    mask = ~(np.isnan(f_vals) | np.isnan(r_vals))
    f = f_vals[mask]
    r = r_vals[mask]
    if len(f) < 100:
        return None
    from scipy.stats import rankdata
    rf = rankdata(f)
    rr = rankdata(r)
    rf_c = rf - np.mean(rf)
    rr_c = rr - np.mean(rr)
    ic = float(np.sum(rf_c * rr_c) / (np.sqrt(np.sum(rf_c**2) * np.sum(rr_c**2)) + 1e-10))
    t_stat = ic * np.sqrt((len(f) - 2) / (1 - ic**2 + 1e-10))
    pval = float(2 * (1 - t_dist.cdf(abs(t_stat), len(f) - 2)))
    return {
        'IC': round(ic, 4),
        'p_value': round(pval, 6),
        'n': int(len(f)),
        'significant': bool(pval < 0.05),
    }
