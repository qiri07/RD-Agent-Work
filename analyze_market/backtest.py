#!/usr/bin/env python3
"""
回测模块（numpy向量化版）
=========================
单只股票的向量化回测引擎。
"""
import numpy as np
import config as cfg

INITIAL_CAPITAL = cfg.BACKTEST_INITIAL_CAPITAL
COMMISSION = cfg.BACKTEST_COMMISSION_RATE
SLIPPAGE = cfg.BACKTEST_SLIPPAGE_RATE


# 策略参数阈值
THRESHOLDS = {
    'momentum_5d': 0.01,
    'momentum_20d': 0.03,
    'reversal_5d': 0.02,
}

STRATEGIES = ['momentum_5d', 'momentum_20d', 'reversal_5d', 'rsi', 'macd']
COL_MAP = {
    'momentum_5d': 'momentum_5d',
    'momentum_20d': 'momentum_20d',
    'reversal_5d': 'reversal_5d',
    'rsi': 'rsi_14',
    'macd': 'macd',
}


def backtest_np(close_arr, factor_arr, strategy_name):
    """向量化回测 — 单次循环同时计算交易和每日净值"""
    cash = float(INITIAL_CAPITAL)
    shares = 0
    trades = 0
    n = len(close_arr)
    valid = ~np.isnan(factor_arr)

    th = THRESHOLDS.get(strategy_name, 0.0)
    is_momentum = strategy_name in ('momentum_5d', 'momentum_20d')
    is_reversal = strategy_name == 'reversal_5d'
    is_rsi = strategy_name == 'rsi'
    is_macd = strategy_name == 'macd'

    vals = []
    for i in range(n):
        c = close_arr[i]
        if not valid[i]:
            vals.append(cash + shares * c)
            continue
        fv = factor_arr[i]

        do_buy = do_sell = False
        if is_momentum:
            do_buy = shares == 0 and fv > th
            do_sell = shares > 0 and fv < -th
        elif is_reversal:
            do_buy = shares == 0 and fv < -th
            do_sell = shares > 0 and fv > th
        elif is_rsi:
            do_buy = shares == 0 and fv < 30
            do_sell = shares > 0 and fv > 70
        elif is_macd:
            do_buy = shares == 0 and fv > 0
            do_sell = shares > 0 and fv < 0

        if do_buy:
            num = int(cash / c * 0.95 / 100) * 100
            if num > 0:
                cash -= c * num * (1 + COMMISSION + SLIPPAGE)
                shares += num
                trades += 1
        elif do_sell:
            cash += c * shares * (1 - COMMISSION - SLIPPAGE)
            trades += 1
            shares = 0

        vals.append(cash + shares * c)

    final = cash + shares * close_arr[-1] * (1 - COMMISSION - SLIPPAGE) if shares > 0 else cash
    ret = (final / INITIAL_CAPITAL - 1) * 100

    v = np.array(vals)
    dr = np.diff(v) / v[:-1]
    dr = dr[~np.isnan(dr)]
    if len(dr) == 0:
        return None
    sp = float(np.mean(dr) / np.std(dr) * np.sqrt(252)) if np.std(dr) > 0 else 0
    mdd = float((v / np.maximum.accumulate(v) - 1).min())

    return {
        'strategy': strategy_name,
        'final_value': round(final, 0),
        'return_pct': round(ret, 2),
        'sharpe': round(sp, 2),
        'max_drawdown_pct': round(mdd*100, 2),
        'n_trades': trades,
    }
