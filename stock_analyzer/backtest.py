#!/usr/bin/env python3
from __future__ import annotations
"""
回测引擎
========
实现单股票回测逻辑，包含 Backtest 类和 run_bt 函数。
"""
import numpy as np
import pandas as pd
from .constants import INITIAL_CAPITAL, COMMISSION, SLIPPAGE


class Backtest:
    """单股票回测器"""

    def __init__(self):
        self.cash = INITIAL_CAPITAL
        self.shares = 0
        self.trades = []
        self.daily = []

    def buy(self, dt, price, n):
        cost = price * n * (1 + COMMISSION + SLIPPAGE)
        if cost <= self.cash:
            self.cash -= cost
            self.shares += n
            self.trades.append({'date': dt, 'action': 'BUY', 'price': price, 'shares': n})
            return True
        return False

    def sell(self, dt, price, n):
        rev = price * n * (1 - COMMISSION - SLIPPAGE)
        self.cash += rev
        self.shares -= n
        self.trades.append({'date': dt, 'action': 'SELL', 'price': price, 'shares': n})
        return True

    def value(self, dt, price):
        return self.cash + self.shares * price


def run_bt(stock_df, factor_df, factor_col, strategy, params=None):
    """运行单只股票的回测

    Args:
        stock_df: 股票价格 DataFrame
        factor_df: 因子 DataFrame
        factor_col: 因子列名
        strategy: 策略类型 ('momentum', 'mean_reversion', 'rsi', 'macd')
        params: 策略参数

    Returns:
        Backtest 实例
    """
    bt = Backtest()
    mrg = pd.merge(
        stock_df.reset_index(),
        factor_df.reset_index(),
        on=['date', 'instrument'], how='inner'
    ).set_index(['date', 'instrument']).sort_index()

    if mrg.empty:
        return bt

    dates = sorted(stock_df.index.get_level_values(0).unique())
    for i, dt in enumerate(dates):
        row = mrg.loc[dt]
        if len(row) != 1:
            continue
        price = float(row['$close'].iloc[0])
        fv = float(row[factor_col].iloc[0]) if factor_col in row else np.nan

        if np.isnan(fv):
            bt.daily.append({'date': dt, 'value': bt.value(dt, price)})
            continue

        if strategy == 'momentum':
            th = params.get('threshold', 0.02)
            if bt.shares == 0 and fv > th:
                n = int(bt.cash / price * 0.95 / 100) * 100
                if n > 0:
                    bt.buy(dt, price, n)
            elif bt.shares > 0 and fv < -th:
                bt.sell(dt, price, bt.shares)
        elif strategy == 'mean_reversion':
            th = params.get('threshold', 0.03)
            if bt.shares == 0 and fv < -th:
                n = int(bt.cash / price * 0.95 / 100) * 100
                if n > 0:
                    bt.buy(dt, price, n)
            elif bt.shares > 0 and fv > th:
                bt.sell(dt, price, bt.shares)
        elif strategy == 'rsi':
            if bt.shares == 0 and fv < 30:
                n = int(bt.cash / price * 0.95 / 100) * 100
                if n > 0:
                    bt.buy(dt, price, n)
            elif bt.shares > 0 and fv > 70:
                bt.sell(dt, price, bt.shares)
        elif strategy == 'macd':
            sig = float(mrg.loc[dt, 'macd_signal'].iloc[0]) if 'macd_signal' in mrg.loc[dt] else np.nan
            if bt.shares == 0 and not np.isnan(sig) and fv > 0 and fv > sig:
                n = int(bt.cash / price * 0.95 / 100) * 100
                if n > 0:
                    bt.buy(dt, price, n)
            elif bt.shares > 0 and not np.isnan(sig) and fv < 0 and fv < sig:
                bt.sell(dt, price, bt.shares)

        if i == len(dates) - 1 and bt.shares > 0:
            bt.sell(dt, price, bt.shares)
        bt.daily.append({'date': dt, 'value': bt.value(dt, price)})

    return bt


# 策略配置
STRATEGY_CONFIG = {
    'momentum_5d':   ('momentum_5d',  'momentum',   {'threshold': 0.01}),
    'momentum_20d':  ('momentum_20d', 'momentum',   {'threshold': 0.03}),
    'reversal_5d':   ('reversal_5d',  'mean_reversion', {'threshold': 0.02}),
    'rsi':           ('rsi_14',       'rsi',        {}),
    'macd':          ('macd',         'macd',       {}),
}


def run_all_backtests(stock, factor_df):
    """运行所有策略的回测，返回结果列表

    Returns:
        list of dicts with strategy performance metrics
    """
    results = []
    for name, (fc, strat, params) in STRATEGY_CONFIG.items():
        if fc not in factor_df.columns:
            continue
        bt = run_bt(stock, factor_df, fc, strat, params)
        final = bt.daily[-1]['value'] if bt.daily else INITIAL_CAPITAL
        ret = (final / INITIAL_CAPITAL - 1) * 100
        vals = pd.Series([v['value'] for v in bt.daily])
        rets = vals.pct_change().dropna()
        sp = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
        dd = (vals / vals.cummax() - 1).min()
        nb = len([t for t in bt.trades if t['action'] == 'BUY'])
        results.append({
            'strategy': name,
            'factor': fc,
            'final_value': final,
            'return_pct': ret,
            'sharpe': sp,
            'max_drawdown_pct': dd * 100,
            'n_trades': nb,
        })
    return results
