#!/usr/bin/env python3
from __future__ import annotations
"""
因子合成模块
=============
多因子加权合成、Top-K 选股、IC 汇总统计。
"""
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
import config as cfg
from .factor_loader import FactorLoader
from .factor_ic import compute_ic_time_series

logger = logging.getLogger(__name__)


def cross_section_zscore(df: pd.DataFrame) -> pd.DataFrame:
    """横截面 Z-score 标准化"""
    result = df.copy()
    for col in df.columns:
        grouped = df[col].groupby(level="datetime", sort=False)
        mean = grouped.transform('mean')
        std = grouped.transform('std')
        result[col] = (df[col] - mean) / std.replace(0, np.nan)
    return result.fillna(0)


def synthesize_factors(
    factors: Dict[str, pd.Series],
    weights: Optional[Dict[str, float]] = None,
    method: str = 'equal'
) -> pd.Series:
    """
    合成多因子得分

    Args:
        factors: {factor_id: Series}
        weights: {factor_id: weight} (None=等权)
        method: 'equal' or 'ic_weighted'

    Returns:
        综合得分 Series
    """
    if not factors or len(factors) == 0:
        return pd.Series(dtype=float)

    combined = pd.DataFrame(factors)
    combined = combined.ffill().fillna(0)
    standardized = cross_section_zscore(combined)

    if weights is None:
        weights = {col: 1.0 / len(combined.columns) for col in combined.columns}

    score_cols = [f"score_{col}" for col in combined.columns]
    for col in combined.columns:
        w = weights.get(col, 0)
        if w > 0:
            standardized[f"score_{col}"] = standardized[col] * w

    composite = standardized[score_cols].sum(axis=1)
    return composite


def get_top_stocks(
    scores: pd.Series,
    top_k: int = 10,
    date: Optional[pd.Timestamp] = None
) -> pd.DataFrame:
    """选取 Top-K 股票"""
    if date is None:
        date = scores.index.get_level_values('datetime').max()

    day_scores = scores.xs(date, level='datetime')
    day_scores = day_scores.dropna()
    if isinstance(day_scores, pd.DataFrame):
        score_col = 'composite_score' if 'composite_score' in day_scores.columns else day_scores.columns[0]
        day_scores = day_scores.sort_values(score_col, ascending=False)
        top_stocks = day_scores.head(top_k)
        result = pd.DataFrame({
            'score': top_stocks[score_col].values,
            'rank': range(1, len(top_stocks) + 1)
        })
    else:
        day_scores = day_scores.sort_values(ascending=False)
        top_stocks = day_scores.head(top_k)
        result = pd.DataFrame({
            'score': top_stocks.values,
            'rank': range(1, len(top_stocks) + 1)
        })
    return result


def compute_factor_ic_summary(
    factor_ids: List[str],
    returns: pd.Series,
    loader: Optional[FactorLoader] = None,
) -> pd.DataFrame:
    """计算因子 IC 汇总统计"""
    if loader is None:
        from .factor_loader import FactorLoader
        loader = FactorLoader()

    results = []
    for fid in factor_ids:
        factor = loader.load_factor(fid)
        if factor is None:
            continue

        ic_by_date = compute_ic_time_series(factor, returns)
        if not ic_by_date:
            continue

        ic_arr = np.array(list(ic_by_date.values()))
        n = len(ic_arr)
        ic_mean = np.nanmean(ic_arr)
        ic_std = np.nanstd(ic_arr) if n > 1 else 0
        ic_t = ic_mean / (ic_std / np.sqrt(max(n - 1, 1)) + 1e-10) if n > 1 else np.nan
        ic_pos = (ic_arr > 0).mean() if n > 0 else np.nan

        results.append({
            'factor_id': fid,
            'IC_5d': ic_mean,
            'IC_t_5d': ic_t,
            'IC_pos_5d': ic_pos,
            'n_days': n,
            'abs_IC': abs(ic_mean),
        })

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values('abs_IC', ascending=False)
    return df.reset_index(drop=True)


def synthesize_daily_composite(
    factor_data: Dict[str, pd.Series],
    weights: Optional[Dict[str, float]] = None,
    date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """
    统一的多因子合成入口：横截面 Z-score + 等权合成。

    供 select_top10.py / run_pipeline.py / backtest_top10.py 等上层脚本复用。
    """
    if not factor_data:
        return pd.DataFrame()

    if date is None:
        # 自动选择数据最完整的日期：取所有因子都有数据的最新日期
        all_dates = []
        for s in factor_data.values():
            s_sorted = s.sort_index()
            nonnull_dates = s_sorted.dropna().index.get_level_values("datetime").unique()
            all_dates.append(set(nonnull_dates))
        if all_dates:
            common_dates = all_dates[0]
            for d in all_dates[1:]:
                common_dates = common_dates & d
            date = max(common_dates) if common_dates else max(s.index.get_level_values("datetime").max() for s in factor_data.values())
        else:
            date = max(s.index.get_level_values("datetime").max() for s in factor_data.values())
    # 确保 date 是 Timestamp 类型，避免类型不匹配
    date = pd.Timestamp(date)
    logger.info("合成综合得分，交易日: %s", date.strftime('%Y-%m-%d'))

    # 提取目标日期的因子截面
    day_series = {}
    for fid, s in factor_data.items():
        s_sorted = s.sort_index()
        mask = s_sorted.index.get_level_values("datetime") == date
        vals = s_sorted[mask].dropna()
        if len(vals) > 0:
            day_series[fid] = vals

    if not day_series:
        logger.warning("没有可用因子数据用于合成")
        return pd.DataFrame()

    logger.info("参与合成的因子数: %d，股票数: %d", len(day_series), len(next(iter(day_series.values()))))

    # 去重：处理可能的重复行（防止 non-unique multi-index 报错）
    df = pd.DataFrame(day_series)
    df = df.reset_index()
    df = df.drop_duplicates(subset=["datetime", "instrument"])

    instrument_col = "instrument"
    for col in df.columns:
        if col not in (instrument_col, "datetime"):
            mean = df[col].mean()
            std = df[col].std()
            df[col] = ((df[col] - mean) / std).fillna(0) if std > 0 else 0.0

    # 等权合成
    factor_cols = [c for c in df.columns if c not in (instrument_col, "datetime")]
    if weights is None:
        weights = {fid: 1.0 / len(factor_cols) for fid in factor_cols}

    score_cols = [f"score_{fid}" for fid in factor_cols]
    for fid in factor_cols:
        w = weights.get(fid, 0)
        if w > 0:
            df[f"score_{fid}"] = df[fid] * w

    df["composite_score"] = df[score_cols].sum(axis=1)
    df["rank"] = df["composite_score"].rank(ascending=False, method="dense").astype(int)
    df = df.sort_values("composite_score", ascending=False)

    factor_cols = [c for c in df.columns if c not in ("rank", instrument_col, "composite_score", "datetime")]
    df = df[["rank", instrument_col, "composite_score"] + factor_cols]

    return df
