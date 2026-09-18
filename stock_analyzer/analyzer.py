#!/usr/bin/env python3
from __future__ import annotations
"""
因子计算与统计
==============
负责单只股票因子计算、收益统计、IC 检验等核心逻辑。
"""
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


def compute_factors(stock: pd.DataFrame, market_df: pd.DataFrame) -> pd.DataFrame:
    """计算单只股票的各类因子

    Args:
        stock: 单只股票价格数据，MultiIndex (date, instrument)
        market_df: 全市场行情数据，用于计算 alpha

    Returns:
        DataFrame with factor columns
    """
    close = stock['$close']
    high = stock['$high']
    low = stock['$low']
    volume = stock['$volume']
    factors = {}

    for p in [5, 10, 20, 60]:
        factors[f'momentum_{p}d'] = close / close.shift(p) - 1
    for p in [3, 5]:
        factors[f'reversal_{p}d'] = -(close / close.shift(p) - 1)
    for p in [10, 20, 60]:
        factors[f'volatility_{p}d'] = close.pct_change().rolling(p).std() * np.sqrt(252)
    factors['amplitude_20d'] = (high - low).rolling(20).mean() / close
    factors['volume_ratio'] = volume / volume.rolling(20).mean()
    factors['volume_momentum_5d'] = volume / volume.shift(5) - 1
    for p in [5, 10, 20]:
        ma = close.rolling(p).mean()
        factors[f'bias_{p}d'] = (close - ma) / ma

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    factors['rsi_14'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    factors['macd'] = ema12 - ema26
    factors['macd_signal'] = factors['macd'].ewm(span=9).mean()
    factors['macd_hist'] = factors['macd'] - factors['macd_signal']

    # 布林带
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    factors['bollinger_pos'] = (close - ma20) / (2 * std20)

    # 相对强弱 (alpha)
    market_close = market_df.groupby('date')['$close'].mean()
    market_ret = market_close.pct_change()
    stock_ret_s = close.pct_change()
    stock_ret_series = pd.Series(
        stock_ret_s.values,
        index=stock_ret_s.index.get_level_values(0),
        name='stock_ret'
    )
    aligned = pd.DataFrame({'stock_ret': stock_ret_series, 'mkt_ret': market_ret}).dropna()
    factors['alpha_20d'] = aligned['stock_ret'].rolling(20).mean() - aligned['mkt_ret'].rolling(20).mean()

    return pd.DataFrame(factors, index=stock.index)


def compute_returns(stock_reset: pd.DataFrame) -> pd.DataFrame:
    """计算收益率序列"""
    stock_reset['ret_1d'] = stock_reset.groupby('instrument')['$close'].pct_change(1)
    stock_reset['ret_5d'] = stock_reset.groupby('instrument')['$close'].pct_change(5)
    return stock_reset


def compute_stats(daily_ret: pd.Series) -> dict:
    """计算基础收益统计

    Returns:
        dict with ann_ret, ann_vol, sharpe, max_dd
    """
    if len(daily_ret) == 0:
        return {"ann_ret": 0.0, "ann_vol": 0.0, "sharpe": 0.0, "max_dd": 0.0}
    ann_ret = (1 + daily_ret).prod() ** (252 / len(daily_ret)) - 1
    ann_vol = daily_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cumret = (1 + daily_ret).cumprod()
    max_dd = (cumret / cumret.cummax() - 1).min()
    return {
        'ann_ret': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'max_dd': max_dd,
    }


def compute_yearly_stats(stock_full: pd.DataFrame) -> list:
    """计算年度统计"""
    yearly_stats = []
    stock_full['year'] = stock_full['date'].dt.year
    for year, grp in stock_full.groupby('year'):
        r = grp['ret_1d'].dropna()
        if len(r) < 100:
            continue
        ar = (1 + r).prod() ** (252 / len(r)) - 1
        vol = r.std() * np.sqrt(252)
        dd = ((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min()
        yearly_stats.append({
            'year': int(year),
            'return_pct': round(ar * 100, 2),
            'volatility_pct': round(vol * 100, 2),
            'max_drawdown_pct': round(dd * 100, 2),
            'trading_days': len(r),
            'win_rate': round((r > 0).mean() * 100, 1),
        })
    return yearly_stats


def compute_ic_records(factor_df: pd.DataFrame, forward_ret: pd.Series) -> list:
    """计算单股票因子 IC 检验记录"""
    ic_records = []
    for col in ['momentum_5d', 'momentum_10d', 'momentum_20d', 'momentum_60d',
                'reversal_5d', 'rsi_14', 'bollinger_pos', 'volume_ratio']:
        if col not in factor_df.columns:
            continue
        f_vals = factor_df[col].dropna()
        common = f_vals.index.intersection(forward_ret.index)
        if len(common) < 100:
            continue
        ic, pval = scipy_stats.spearmanr(f_vals.loc[common], forward_ret.loc[common])
        sig = pval < 0.05
        ic_records.append({
            'factor': col,
            'n_samples': len(common),
            'IC': round(ic, 6),
            'p_value': round(pval, 6),
            'significant': sig,
        })
    return ic_records
