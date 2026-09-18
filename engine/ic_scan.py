#!/usr/bin/env python3
from __future__ import annotations
"""
因子 IC 分析引擎模块（向后兼容入口）
=====================================
核心逻辑已迁移到 engine/ic_scan/ 子包。

用法:
    from engine.ic_scan import compute_ic, ic_analysis, run_ic_scan
"""
from .core import (
    compute_ic,
    IC_FORWARD_DAYS,
    IC_WINSORIZE,
    IC_MIN_STOCKS_PER_DAY,
)
from .analysis import ic_analysis
from .data import load_returns_from_sessions, validate_data_consistency
from .orchestrator import run_ic_scan

__all__ = [
    'compute_ic',
    'ic_analysis',
    'load_returns_from_sessions',
    'validate_data_consistency',
    'run_ic_scan',
    'IC_FORWARD_DAYS',
    'IC_WINSORIZE',
    'IC_MIN_STOCKS_PER_DAY',
]
