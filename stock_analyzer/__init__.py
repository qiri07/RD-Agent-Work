#!/usr/bin/env python3
from __future__ import annotations
"""
股票分析器包
============
提供单只股票全量分析功能。

用法:
    from stock_analyzer import analyze_stock
    analyze_stock('SH601668')
    analyze_stock('中国建筑')
"""
from .resolver import resolve_ticker
from .analyzer import (
    compute_factors,
    compute_returns,
    compute_stats,
    compute_yearly_stats,
    compute_ic_records,
)
from .backtest import run_bt, run_all_backtests, Backtest, STRATEGY_CONFIG
from .report import generate_report, save_cross_sectional_ic, save_ranking
from .constants import INITIAL_CAPITAL, COMMISSION, SLIPPAGE

__all__ = [
    'resolve_ticker',
    'compute_factors',
    'compute_returns',
    'compute_stats',
    'compute_yearly_stats',
    'compute_ic_records',
    'run_bt',
    'run_all_backtests',
    'Backtest',
    'STRATEGY_CONFIG',
    'generate_report',
    'save_cross_sectional_ic',
    'save_ranking',
    'INITIAL_CAPITAL',
    'COMMISSION',
    'SLIPPAGE',
]
