#!/usr/bin/env python3
from __future__ import annotations
"""
因子重算 + IC分析 引擎模块（向后兼容入口）
============================================
核心逻辑已迁移到 engine/recompute/ 子包。

用法:
    from engine.recompute import (
        run_phase1_recompute, run_phase2_ic_analysis,
        ic_analysis_yearly, generate_ic_report, print_summary, run_full_recompute,
    )
"""
from .loader import load_factor_results, load_returns
from .ic_analysis import ic_analysis_yearly, generate_ic_report
from .orchestrator import run_phase1_recompute, run_phase2_ic_analysis
from .report import print_summary, run_full_recompute

# Backward compatibility: tests mock _load_factor_results and _load_returns
_load_factor_results = load_factor_results
_load_returns = load_returns

__all__ = [
    'run_phase1_recompute',
    'run_phase2_ic_analysis',
    'ic_analysis_yearly',
    'generate_ic_report',
    'print_summary',
    'run_full_recompute',
]
