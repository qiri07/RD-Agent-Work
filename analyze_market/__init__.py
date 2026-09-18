#!/usr/bin/env python3
from __future__ import annotations
"""
analyze_market 包公共 API
==========================
"""
from .factors import compute_all_factors_np, compute_forward_ret_np
from .stats import stock_stats_np, ic_numpy
from .backtest import backtest_np, THRESHOLDS, STRATEGIES, COL_MAP

# Backward compatibility aliases
FACTOR_COLS = [
    'momentum_5d', 'momentum_10d', 'momentum_20d', 'momentum_60d',
    'reversal_5d', 'rsi_14', 'bollinger_pos', 'volume_ratio'
]

__all__ = [
    'compute_all_factors_np',
    'compute_forward_ret_np',
    'stock_stats_np',
    'ic_numpy',
    'backtest_np',
    'THRESHOLDS',
    'STRATEGIES',
    'COL_MAP',
    'FACTOR_COLS',
]
