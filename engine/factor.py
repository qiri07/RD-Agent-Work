#!/usr/bin/env python3
from __future__ import annotations
"""
因子计算引擎模块（向后兼容入口）
=================================
提供 FactorEngine 类，内部逻辑分布在 factor_loader / factor_ic / factor_synthesize 子模块。

用法:
    from engine.factor import FactorEngine, create_factor_engine, synthesize_daily_composite
"""
import logging
from typing import Dict, List, Optional
from pathlib import Path

import pandas as pd
import numpy as np

from .factor_loader import FactorLoader
from .factor_ic import compute_single_ic, compute_ic_time_series
from .factor_synthesize import (
    synthesize_factors,
    get_top_stocks,
    compute_factor_ic_summary,
    synthesize_daily_composite,
)

logger = logging.getLogger(__name__)


class FactorEngine:
    """因子计算引擎 — 统一入口，内部委托给子模块"""

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = workspace or Path('.')
        self._loader = FactorLoader(workspace)

    # ── 加载 ──────────────────────────────────────────────
    def load_factor(self, factor_id: str):
        return self._loader.load_factor(factor_id)

    def load_factors(self, factor_ids):
        return self._loader.load_factors(factor_ids)

    _normalize_index = staticmethod(FactorLoader._normalize_index)

    # ── IC 计算 ───────────────────────────────────────────
    def compute_ic(self, factor: pd.Series, returns: pd.Series) -> float:
        return compute_single_ic(factor, returns)

    def compute_ic_time_series(self, factor: pd.Series, returns: pd.Series) -> Dict[pd.Timestamp, float]:
        return compute_ic_time_series(factor, returns)

    # ── 横截面标准化 ──────────────────────────────────────
    @staticmethod
    def cross_section_zscore(df: pd.DataFrame) -> pd.DataFrame:
        """横截面 Z-score 标准化"""
        result = df.copy()
        for col in df.columns:
            grouped = df[col].groupby(level="datetime", sort=False)
            mean = grouped.transform('mean')
            std = grouped.transform('std')
            result[col] = (df[col] - mean) / std.replace(0, np.nan)
        return result.fillna(0)

    # ── 因子合成 ──────────────────────────────────────────
    def synthesize_factors(self, factors, weights=None, method='equal'):
        return synthesize_factors(factors, weights, method)

    def get_top_stocks(self, scores, top_k=10, date=None):
        return get_top_stocks(scores, top_k, date)

    def compute_factor_ic_summary(self, factor_ids, returns, workspace=None):
        from .factor_synthesize import compute_factor_ic_summary
        loader = FactorLoader(workspace or self.workspace)
        return compute_factor_ic_summary(factor_ids, returns, loader=loader)


def create_factor_engine(workspace: Optional[Path] = None) -> FactorEngine:
    """工厂函数：创建因子引擎"""
    return FactorEngine(workspace)


__all__ = [
    'FactorEngine',
    'create_factor_engine',
    'synthesize_daily_composite',
]
