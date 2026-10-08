#!/usr/bin/env python3
from __future__ import annotations
"""
白名单因子计算模块
==================
共享的白名单数据加载和因子计算逻辑，供 whitelist_pipeline 和
whitelist_backtest 等模块复用，避免代码重复。

因子列表:
  momentum_5d, momentum_10d, momentum_20d   — 5/10/20日动量
  reversal_5d                              — 5日反转
  volatility_20d                           — 20日波动率（年化）
  rsi_14                                   — 14日RSI
  macd                                     — MACD线
  bollinger_pos                            — 布林带位置（标准差单位）
  volume_ratio                             — 当日成交量/20日均量
"""
import logging
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)


# ─── 数据加载 ─────────────────────────────────────────────────────────────────

def load_whitelist_data(whitelist: list[str] | None = None) -> pd.DataFrame:
    """加载并过滤白名单价格数据

    Args:
        whitelist: 股票代码列表（默认使用 cfg.WHITELIST_STOCKS）

    Returns:
        MultiIndex DataFrame (datetime, instrument)，已排序去重
    """
    targets = whitelist or cfg.WHITELIST_STOCKS
    if not targets:
        raise ValueError("白名单为空，请在 .env 中配置 WHITELIST_STOCKS")

    df = pd.read_parquet(cfg.DAILY_PV_FULL_PQ)
    mask = df.index.get_level_values('instrument').isin(targets)
    df = df[mask].copy()
    df.index = df.index.set_names(['datetime', 'instrument'])
    df = df.sort_index()
    df = df[~df.index.duplicated(keep='first')]

    n_inst = df.index.get_level_values('instrument').nunique()
    logger.info("白名单数据: %d 行, %d 只股票", len(df), n_inst)
    logger.info("   日期范围: %s ~ %s",
                df.index.get_level_values('datetime').min().date(),
                df.index.get_level_values('datetime').max().date())
    return df


# ─── 因子计算 ─────────────────────────────────────────────────────────────────

FACTOR_NAMES = [
    'momentum_5d', 'momentum_10d', 'momentum_20d',
    'reversal_5d', 'volatility_20d', 'rsi_14',
    'macd', 'bollinger_pos', 'volume_ratio',
    # 补充技术因子（来自 multi_agent_quant 8策略投票融合）
    'cci_14', 'kdj_k', 'kdj_d', 'kdj_j',
    'plus_di', 'minus_di', 'adx_14',
]


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """计算白名单股票的 9 个因子

    Args:
        df: 价格 DataFrame，MultiIndex (datetime, instrument)

    Returns:
        因子 DataFrame，MultiIndex (datetime, instrument)，列名 = 因子名
    """
    logger.info("计算因子...")

    all_insts = df.index.get_level_values('instrument').unique()
    all_rows: list[tuple] = []

    for inst in all_insts:
        stock = df.xs(inst, level='instrument')
        close = stock['$close'].values
        high  = stock['$high'].values
        low   = stock['$low'].values
        volume = stock['$volume'].values
        dates = stock.index

        # ── 动量因子 ──
        for period in (5, 10, 20):
            name = f'momentum_{period}d'
            result = np.full(len(close), np.nan)
            for i in range(period, len(close) - period):
                result[i] = close[i] / close[i - period] - 1
            result = np.roll(result, -period)
            result[-period:] = np.nan
            for d, r in zip(dates, result):
                all_rows.append((d, inst, name, r))

        # ── 反转因子 ──
        name = 'reversal_5d'
        result = np.full(len(close), np.nan)
        for i in range(5, len(close) - 5):
            result[i] = -(close[i] / close[i - 5] - 1)
        result = np.roll(result, -5)
        result[-5:] = np.nan
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))

        # ── 波动率因子 ──
        name = 'volatility_20d'
        rets = np.diff(np.log(close))
        result = np.full(len(close), np.nan)
        for i in range(20, len(close)):
            result[i] = np.std(rets[i - 20:i], ddof=1) * np.sqrt(252)
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))

        # ── RSI 因子 ──
        name = 'rsi_14'
        delta = np.diff(close)
        gain = np.maximum(delta, 0)
        loss = np.maximum(-delta, 0)
        result = np.full(len(close), np.nan)
        for i in range(14, len(close)):
            avg_g = np.mean(gain[i - 14:i])
            avg_l = np.mean(loss[i - 14:i])
            if avg_l == 0:
                result[i] = 50.0 if avg_g == 0 else 100.0
            else:
                result[i] = 100 - 100 / (1 + avg_g / avg_l)
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))

        # ── MACD 因子 ──
        name = 'macd'
        result = np.full(len(close), np.nan)
        ema12, ema26 = close[0], close[0]
        k12, k26 = 2 / 13, 2 / 27
        for i in range(1, len(close)):
            ema12 = close[i] * k12 + ema12 * (1 - k12)
            ema26 = close[i] * k26 + ema26 * (1 - k26)
            result[i] = ema12 - ema26
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))

        # ── 布林带位置因子 ──
        name = 'bollinger_pos'
        result = np.full(len(close), np.nan)
        for i in range(20, len(close)):
            ma = np.mean(close[i - 20:i])
            sd = np.std(close[i - 20:i], ddof=1)
            if sd > 0:
                result[i] = (close[i] - ma) / (2 * sd)
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))

        # ── 成交量比率因子 ──
        name = 'volume_ratio'
        result = np.full(len(close), np.nan)
        for i in range(20, len(close)):
            ma = np.mean(volume[i - 20:i])
            if ma > 0:
                result[i] = volume[i] / ma
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))

        # ── CCI / KDJ / ADX（需要 $high / $low 列）──────────────
        if "high" in stock.columns or "$high" in stock.columns:
            high_key = "high" if "high" in stock.columns else "$high"
            low_key  = "low"  if "low"  in stock.columns else "$low"
            high = stock[high_key].values
            low  = stock[low_key].values

            # ── CCI ──
            name = 'cci_14'
            typical = (high + low + close) / 3
            result = np.full(len(close), np.nan)
            for i in range(14, len(close)):
                window = typical[i - 14:i]
                sma  = window.mean()
                mad  = np.abs(window - sma).mean()
                if mad > 0:
                    result[i] = (typical[i] - sma) / (0.015 * mad)
            for d, r in zip(dates, result):
                all_rows.append((d, inst, name, r))

            # ── KDJ ──
            period = 9
            rsv = np.full(len(close), np.nan)
            for i in range(period - 1, len(close)):
                ln  = np.min(low[i - period + 1:i + 1])
                hn  = np.max(high[i - period + 1:i + 1])
                denom = hn - ln
                if denom > 0:
                    rsv[i] = (close[i] - ln) / denom * 100
            k_vals = np.full(len(close), np.nan)
            d_vals = np.full(len(close), np.nan)
            k_ema = d_ema = 0.0
            init_k = init_d = False
            for i in range(len(close)):
                if not np.isnan(rsv[i]):
                    if not init_k:
                        k_ema = rsv[i]; init_k = True
                    else:
                        k_ema = k_ema * 0.5 + rsv[i] * 0.5
                    k_vals[i] = k_ema
                if not np.isnan(k_vals[i]):
                    if not init_d:
                        d_ema = k_vals[i]; init_d = True
                    else:
                        d_ema = d_ema * 0.5 + k_vals[i] * 0.5
                    d_vals[i] = d_ema
            j_vals = 3 * k_vals - 2 * d_vals
            for i in range(len(close)):
                if not np.isnan(k_vals[i]):
                    all_rows.append((dates[i], inst, 'kdj_k', k_vals[i]))
                if not np.isnan(d_vals[i]):
                    all_rows.append((dates[i], inst, 'kdj_d', d_vals[i]))
                all_rows.append((dates[i], inst, 'kdj_j', j_vals[i]))

            # ── ADX ──
            tr_arr = np.maximum(high - low,
                         np.maximum(np.abs(high - np.roll(close, 1)),
                                    np.abs(low  - np.roll(close, 1))))
            dh = np.diff(high); dl = -np.diff(low)
            plus_dm_raw = np.where((dh > dl) & (dh > 0), dh, 0)
            minus_dm_raw = np.where((dl > dh) & (dl > 0), dl, 0)
            plus_dm  = np.insert(plus_dm_raw,  0, 0.0)
            minus_dm = np.insert(minus_dm_raw, 0, 0.0)
            atr_p = np.convolve(tr_arr, np.ones(14) / 14, mode='valid')
            atr_p = np.concatenate([np.full(13, np.nan), atr_p])
            pd_raw = np.convolve(plus_dm,  np.ones(14) / 14, mode='valid')
            md_raw = np.convolve(minus_dm, np.ones(14) / 14, mode='valid')
            plus_di  = 100 * np.concatenate([np.full(13, np.nan), pd_raw]) / np.maximum(atr_p, 1e-10)
            minus_di = 100 * np.concatenate([np.full(13, np.nan), md_raw]) / np.maximum(atr_p, 1e-10)
            dx  = 100 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-10)
            adx_ = np.convolve(dx, np.ones(14) / 14, mode='valid')
            adx_ = np.concatenate([np.full(13, np.nan), adx_])
            for i in range(len(close)):
                if not np.isnan(plus_di[i]):
                    all_rows.append((dates[i], inst, 'plus_di',  plus_di[i]))
                if not np.isnan(minus_di[i]):
                    all_rows.append((dates[i], inst, 'minus_di', minus_di[i]))
                if not np.isnan(adx_[i]):
                    all_rows.append((dates[i], inst, 'adx_14',   adx_[i]))
    result_df = pd.DataFrame(all_rows, columns=['datetime', 'instrument', 'factor', 'value'])
    factors_df = result_df.pivot(index=['datetime', 'instrument'],
                                  columns='factor', values='value')
    factors_df.index.names = ['datetime', 'instrument']
    factors_df = factors_df.sort_index()

    for fname in FACTOR_NAMES:
        if fname in factors_df.columns:
            valid = factors_df[fname].dropna().shape[0]
            logger.info("  %s: %d 有效值", fname, valid)

    return factors_df


# ─── IC 分析 ──────────────────────────────────────────────────────────────────

def compute_ic(factors_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """计算因子 IC（Spearman 秩相关）

    Args:
        factors_df: 因子 DataFrame
        df: 价格 DataFrame

    Returns:
        IC 汇总 DataFrame，列: factor_id, IC_5d, IC_t_5d, IC_pos_5d, n_days
    """
    from scipy.stats import spearmanr

    logger.info("计算 IC...")

    if df.empty or len(df) == 0:
        logger.warning("价格数据为空，跳过 IC 计算")
        return pd.DataFrame()

    # 计算 forward returns（5日）
    returns_data = []
    for inst in df.index.get_level_values('instrument').unique():
        stock = df.xs(inst, level='instrument')
        close = stock['$close'].values
        fwd_ret = np.full(len(close), np.nan)
        for i in range(5, len(close) - 5):
            fwd_ret[i] = close[i + 5] / close[i] - 1
        for d, r in zip(stock.index, fwd_ret):
            returns_data.append((d, inst, r))

    returns_df = pd.DataFrame(returns_data,
                               columns=['datetime', 'instrument', 'return'])
    returns_df.set_index(['datetime', 'instrument'], inplace=True)

    ic_results = []

    for fid in factors_df.columns:
        merged = pd.DataFrame({
            'factor': factors_df[fid].values,
            'return': returns_df['return'].values
        }, index=factors_df.index)
        merged = merged.dropna()

        if len(merged) < 50:
            continue

        daily_ics = []
        for date, group in merged.groupby(level='datetime'):
            if len(group) < 3:
                continue
            f_vals = group['factor'].values
            r_vals = group['return'].values
            ic_val, _ = spearmanr(f_vals, r_vals)
            if np.isfinite(ic_val):
                daily_ics.append(ic_val)

        if len(daily_ics) < 5:
            continue

        ic_mean = np.mean(daily_ics)
        ic_std = np.std(daily_ics)
        ic_t = ic_mean / (ic_std / np.sqrt(len(daily_ics))) if ic_std > 0 else 0
        ic_pos = sum(1 for x in daily_ics if x > 0) / len(daily_ics)

        ic_results.append({
            'factor_id': fid,
            'IC_5d': ic_mean,
            'IC_t_5d': ic_t,
            'IC_pos_5d': ic_pos,
            'n_days': len(daily_ics),
        })
        logger.info("  %s: IC=%+.4f, t=%.2f, pos=%.1%%",
                    fid, ic_mean, ic_t, ic_pos * 100)

    if not ic_results:
        return pd.DataFrame()

    ic_df = pd.DataFrame(ic_results).sort_values('IC_5d', key=abs, ascending=False)
    return ic_df


# ─── 因子合成 ─────────────────────────────────────────────────────────────────

def synthesize_score(day_factors: dict) -> pd.DataFrame | None:
    """合成因子得分（横截面 Z-score + 等权）

    Args:
        day_factors: {factor_name: Series(datetime, instrument, value)}

    Returns:
        按 composite_score 降序排列的 DataFrame
    """
    if not day_factors:
        return None
    df = pd.DataFrame(day_factors)
    for col in df.columns:
        mean = df[col].mean()
        std = df[col].std()
        df[col] = ((df[col] - mean) / std).fillna(0) if std > 0 else 0
    n_factors = len(df.columns)
    df['composite_score'] = df.sum(axis=1) / n_factors
    df['rank'] = df['composite_score'].rank(ascending=False, method='dense').astype(int)
    return df.sort_values('composite_score', ascending=False)


__all__ = [
    'load_whitelist_data',
    'compute_factors',
    'compute_ic',
    'synthesize_score',
    'FACTOR_NAMES',
]
