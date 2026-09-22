#!/usr/bin/env python3
from __future__ import annotations
"""
engine/factor_ic.py 测试
=========================
测试 IC 计算模块的所有函数。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from engine.factor_ic import compute_single_ic, compute_ic_time_series


class TestComputeSingleIC(unittest.TestCase):
    """测试 compute_single_ic()"""

    def test_basic_spearman_ic(self):
        """基本 Spearman IC 计算"""
        np.random.seed(42)
        n = 200
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-01"), f"SH{i:06d}") for i in range(n)],
            names=["datetime", "instrument"])
        factor = pd.Series(np.random.randn(n), index=idx)
        returns = pd.Series(np.random.randn(n), index=idx)
        result = compute_single_ic(factor, returns)
        self.assertIsInstance(result, float)
        self.assertTrue(np.isfinite(result))

    def test_perfect_correlation(self):
        """完美正相关 IC=1"""
        n = 100
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-01"), f"SH{i:06d}") for i in range(n)],
            names=["datetime", "instrument"])
        factor = pd.Series(range(n), index=idx, dtype=float)
        returns = pd.Series(range(n), index=idx, dtype=float)
        result = compute_single_ic(factor, returns)
        self.assertAlmostEqual(result, 1.0, places=5)

    def test_negative_correlation(self):
        """完美负相关 IC=-1"""
        n = 100
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-01"), f"SH{i:06d}") for i in range(n)],
            names=["datetime", "instrument"])
        factor = pd.Series(range(n), index=idx, dtype=float)
        returns = pd.Series(range(n, 0, -1), index=idx, dtype=float)
        result = compute_single_ic(factor, returns)
        self.assertAlmostEqual(result, -1.0, places=5)

    def test_insufficient_data(self):
        """数据不足时应返回 NaN"""
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-01"), f"SH{i:06d}") for i in range(10)],
            names=["datetime", "instrument"])
        factor = pd.Series(np.random.randn(10), index=idx)
        returns = pd.Series(np.random.randn(10), index=idx)
        result = compute_single_ic(factor, returns)
        self.assertTrue(np.isnan(result))

    def test_nan_handling(self):
        """含 NaN 的数据应正确跳过"""
        n = 150
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-01"), f"SH{i:06d}") for i in range(n)],
            names=["datetime", "instrument"])
        factor = pd.Series(np.random.randn(n), index=idx)
        factor.iloc[:10] = np.nan  # 10个NaN
        returns = pd.Series(np.random.randn(n), index=idx)
        result = compute_single_ic(factor, returns)
        self.assertTrue(np.isfinite(result))


class TestComputeICTimeSeries(unittest.TestCase):
    """测试 compute_ic_time_series()"""

    def _make_multi_day_data(self, n_dates=10, n_stocks=100):
        dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
        insts = [f"SH{i:06d}" for i in range(100, 100 + n_stocks)]
        np.random.seed(42)
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        factor = pd.Series(np.random.randn(len(idx)), index=idx)
        returns = pd.Series(np.random.randn(len(idx)), index=idx)
        return factor, returns

    def test_returns_dict(self):
        """应返回字典"""
        factor, returns = self._make_multi_day_data()
        result = compute_ic_time_series(factor, returns)
        self.assertIsInstance(result, dict)

    def test_daily_ics_finite(self):
        """每日 IC 应为有限值"""
        factor, returns = self._make_multi_day_data()
        result = compute_ic_time_series(factor, returns)
        for v in result.values():
            self.assertTrue(np.isfinite(v))

    def test_insufficient_daily_data(self):
        """每日股票数不足时应跳过"""
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        insts = ["SH600000"]  # 只有1只股票
        np.random.seed(42)
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        factor = pd.Series(np.random.randn(len(idx)), index=idx)
        returns = pd.Series(np.random.randn(len(idx)), index=idx)
        result = compute_ic_time_series(factor, returns)
        # 每天只有1只股票，少于50的阈值 → 空字典
        self.assertEqual(len(result), 0)

    def test_empty_data(self):
        """空数据应返回空字典"""
        idx = pd.MultiIndex.from_tuples([], names=["datetime", "instrument"])
        factor = pd.Series(dtype=float, index=idx)
        returns = pd.Series(dtype=float, index=idx)
        result = compute_ic_time_series(factor, returns)
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
