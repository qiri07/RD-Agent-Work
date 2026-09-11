#!/usr/bin/env python3
"""
Engine 模块初始化
=================
统一导入所有引擎模块。
"""
from engine.pricing import PriceEngine, load_and_adjust_prices
from engine.backtest import BacktestEngine, BacktestResult, create_backtest_engine
from engine.factor import FactorEngine, create_factor_engine, synthesize_daily_composite
from engine.metrics import PerformanceAnalyzer, PerformanceMetrics, create_performance_analyzer
from engine.cache import get_cache, clear_global_cache, load_cached_parquet, load_cached_hdf
from engine.recompute import (
    run_phase1_recompute, run_phase2_ic_analysis,
    ic_analysis_yearly, generate_ic_report, print_summary, run_full_recompute,
)
from engine.ic_scan import compute_ic, ic_analysis, run_ic_scan, IC_FORWARD_DAYS, IC_MIN_STocks_PER_DAY

__all__ = [
    'PriceEngine',
    'load_and_adjust_prices',
    'BacktestEngine',
    'BacktestResult',
    'create_backtest_engine',
    'FactorEngine',
    'create_factor_engine',
    'synthesize_daily_composite',
    'PerformanceAnalyzer',
    'PerformanceMetrics',
    'create_performance_analyzer',
    'get_cache',
    'clear_global_cache',
    'load_cached_parquet',
    'load_cached_hdf',
    'run_phase1_recompute',
    'run_phase2_ic_analysis',
    'ic_analysis_yearly',
    'generate_ic_report',
    'print_summary',
    'run_full_recompute',
    'compute_ic',
    'ic_analysis',
    'run_ic_scan',
    'IC_FORWARD_DAYS',
    'IC_MIN_STocks_PER_DAY',
]
