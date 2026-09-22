#!/usr/bin/env python3
from __future__ import annotations
"""
engine/factor_synthesize.py 测试
================================
测试因子合成模块的所有函数。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.factor_synthesize import (
    cross_section_zscore,
    synthesize_factors,
    get_top_stocks,
    compute_factor_ic_summary,
    synthesize_daily_composite,
)


class TestCrossSectionZscore(unittest.TestCase):
    """测试 cross_section_zscore()"""

    def test_basic_zscore(self):
        """基本横截面标准化"""
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        insts = [f"SH{i:06d}" for i in range(100, 103)]
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        data = {
            "factor_a": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
            "factor_b": [3.0, 1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0, 2.0],
        }
        df = pd.DataFrame(data, index=idx)
        result = cross_section_zscore(df)
        self.assertEqual(result.shape, df.shape)
        # 每天的均值应接近0
        for d in dates:
            day_mean = result.xs(d, level="datetime")["factor_a"].mean()
            self.assertAlmostEqual(day_mean, 0.0, places=5)

    def test_zscore_constant_column(self):
        """常数列 std=0，应填充为0"""
        dates = pd.date_range("2024-01-01", periods=2, freq="B")
        insts = ["SH600000", "SH600001"]
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        df = pd.DataFrame({"factor_a": [5.0, 5.0, 5.0, 5.0]}, index=idx)
        result = cross_section_zscore(df)
        self.assertTrue((result["factor_a"] == 0).all())

    def test_zscore_preserves_index(self):
        """索引应保持不变"""
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        insts = ["SH600000", "SH600001"]
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        df = pd.DataFrame({"factor_a": range(6)}, index=idx)
        result = cross_section_zscore(df)
        self.assertEqual(result.index.names, idx.names)


class TestSynthesizeFactors(unittest.TestCase):
    """测试 synthesize_factors()"""

    def _make_series(self, values, date="2024-01-01"):
        insts = [f"SH{i:06d}" for i in range(100, 100 + len(values))]
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp(date), inst) for inst in insts],
            names=["datetime", "instrument"])
        return pd.Series(values, index=idx)

    def test_synthesize_equal_weight(self):
        """等权合成"""
        factors = {
            "factor_a": self._make_series([1.0, 2.0, 3.0]),
            "factor_b": self._make_series([3.0, 1.0, 2.0]),
        }
        result = synthesize_factors(factors)
        self.assertIsInstance(result, pd.Series)
        self.assertEqual(len(result), 3)

    def test_synthesize_empty(self):
        """空输入应返回空 Series"""
        result = synthesize_factors({})
        self.assertTrue(result.empty)

    def test_synthesize_with_weights(self):
        """加权合成"""
        factors = {
            "factor_a": self._make_series([1.0, 2.0, 3.0]),
            "factor_b": self._make_series([3.0, 1.0, 2.0]),
        }
        weights = {"factor_a": 0.7, "factor_b": 0.3}
        result = synthesize_factors(factors, weights=weights)
        self.assertIsInstance(result, pd.Series)
        self.assertEqual(len(result), 3)


class TestGetTopStocks(unittest.TestCase):
    """测试 get_top_stocks()"""

    def test_get_top_stocks(self):
        """选取 Top-K 股票"""
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        insts = [f"SH{i:06d}" for i in range(100, 105)]
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        scores = pd.Series(np.random.rand(15), index=idx, name="composite_score")
        result = get_top_stocks(scores, top_k=3)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 3)
        self.assertIn("rank", result.columns)

    def test_get_top_stocks_with_date(self):
        """指定日期选取"""
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        insts = [f"SH{i:06d}" for i in range(100, 105)]
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        scores = pd.Series(np.random.rand(15), index=idx, name="composite_score")
        result = get_top_stocks(scores, top_k=2, date=pd.Timestamp("2024-01-02"))
        self.assertEqual(len(result), 2)


class TestComputeFactorICSummary(unittest.TestCase):
    """测试 compute_factor_ic_summary()"""

    def test_compute_ic_summary_empty_loader(self):
        """因子文件不存在时应返回空 DataFrame"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from engine.factor_loader import FactorLoader
            loader = FactorLoader(workspace=Path(tmpdir))
            result = compute_factor_ic_summary(["nonexistent_factor"], pd.Series())
            self.assertIsInstance(result, pd.DataFrame)
            self.assertTrue(result.empty)


class TestSynthesizeDailyComposite(unittest.TestCase):
    """测试 synthesize_daily_composite()"""

    def _make_series(self, values, date="2024-01-01"):
        insts = [f"SH{i:06d}" for i in range(100, 100 + len(values))]
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp(date), inst) for inst in insts],
            names=["datetime", "instrument"])
        return pd.Series(values, index=idx)

    def test_synthesize_daily_composite_basic(self):
        """基本合成"""
        factor_data = {
            "factor_a": self._make_series([1.0, 2.0, 3.0, 4.0, 5.0]),
            "factor_b": self._make_series([5.0, 4.0, 3.0, 2.0, 1.0]),
        }
        result = synthesize_daily_composite(factor_data)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertIn("composite_score", result.columns)
        self.assertIn("rank", result.columns)

    def test_synthesize_daily_composite_empty(self):
        """空输入应返回空 DataFrame"""
        result = synthesize_daily_composite({})
        self.assertTrue(result.empty)

    def test_synthesize_daily_composite_with_weights(self):
        """带权重的合成"""
        factor_data = {
            "factor_a": self._make_series([1.0, 2.0, 3.0]),
            "factor_b": self._make_series([3.0, 1.0, 2.0]),
        }
        weights = {"factor_a": 0.7, "factor_b": 0.3}
        result = synthesize_daily_composite(factor_data, weights=weights)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertIn("composite_score", result.columns)

    def test_synthesize_daily_composite_dedup(self):
        """重复索引应去重"""
        insts = [f"SH{i:06d}" for i in range(100, 103)]
        idx = pd.MultiIndex.from_tuples([
            (pd.Timestamp("2024-01-01"), "SH600100"),
            (pd.Timestamp("2024-01-01"), "SH600100"),  # 重复
            (pd.Timestamp("2024-01-01"), "SH600101"),
        ], names=["datetime", "instrument"])
        factor_data = {"factor_a": pd.Series([1.0, 2.0, 3.0], index=idx)}
        result = synthesize_daily_composite(factor_data)
        self.assertIsInstance(result, pd.DataFrame)


if __name__ == "__main__":
    unittest.main()
