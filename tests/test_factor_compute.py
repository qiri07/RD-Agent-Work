#!/usr/bin/env python3
from __future__ import annotations
"""
engine/factor_compute.py 测试
==============================
测试白名单因子计算、IC分析和因子合成的所有函数。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.factor_compute import (
    load_whitelist_data, compute_factors, compute_ic, synthesize_score, FACTOR_NAMES
)


def _make_price_df(instruments, dates):
    """构造测试用价格 DataFrame"""
    rows = []
    np.random.seed(42)
    for inst in instruments:
        price = 10.0
        for d in dates:
            price *= 1 + np.random.randn() * 0.01
            rows.append({
                "date": d, "instrument": inst,
                "$open": price, "$close": price * (1 + np.random.randn() * 0.005),
                "$high": price * 1.02, "$low": price * 0.98,
                "$volume": int(1_000_000 * (1 + np.random.randn() * 0.1)),
                "$factor": 1.0,
            })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index(["date", "instrument"])
    df.index.names = ["datetime", "instrument"]
    return df


class TestLoadWhitelistData(unittest.TestCase):
    """测试 load_whitelist_data()"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.pq_path = Path(self.tmpdir.name) / "daily_pv_full.parquet"
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        instruments = ["SH600000", "SH600001", "SZ000001"]
        df = _make_price_df(instruments, dates)
        df.to_parquet(self.pq_path)
        self._pq_path = self.pq_path
        self._tmpdir = self.tmpdir

    def tearDown(self):
        self.tmpdir.cleanup()

    def _patch(self, whitelist):
        import config as cfg
        import engine.factor_compute as fc
        cfg.DAILY_PV_FULL_PQ = self._pq_path
        cfg.WHITELIST_STOCKS = whitelist
        cfg._WHITELIST_RAW = ",".join(whitelist)
        fc.cfg = cfg

    def test_returns_dataframe(self):
        self._patch(["SH600000", "SH600001"])
        result = load_whitelist_data()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(result.index.names, ["datetime", "instrument"])

    def test_filters_by_whitelist(self):
        self._patch(["SH600000"])
        result = load_whitelist_data()
        insts = set(result.index.get_level_values("instrument").unique())
        self.assertEqual(insts, {"SH600000"})

    def test_sorted_and_deduped(self):
        self._patch(["SH600000"])
        result = load_whitelist_data()
        self.assertTrue(result.index.is_monotonic_increasing)
        self.assertFalse(result.index.duplicated().any())

    def test_empty_whitelist_raises(self):
        self._patch([])
        with self.assertRaises(ValueError):
            load_whitelist_data()


class TestComputeFactors(unittest.TestCase):
    """测试 compute_factors()"""

    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=40, freq="B")
        instruments = ["SH600000", "SZ000001"]
        self.df = _make_price_df(instruments, dates)

    def test_all_factors_computed(self):
        result = compute_factors(self.df)
        expected = {
            "momentum_5d", "momentum_10d", "momentum_20d",
            "reversal_5d", "volatility_20d", "rsi_14",
            "macd", "bollinger_pos", "volume_ratio",
        }
        self.assertTrue(expected.issubset(set(result.columns)))
        self.assertEqual(set(result.columns), expected)

    def test_factor_shapes(self):
        result = compute_factors(self.df)
        n_dates = self.df.index.get_level_values("datetime").nunique()
        n_inst = self.df.index.get_level_values("instrument").nunique()
        self.assertEqual(result.shape[0], n_dates * n_inst)

    def test_momentum_valid_range(self):
        result = compute_factors(self.df)
        m5 = result["momentum_5d"].dropna()
        self.assertGreater(len(m5), 0)
        self.assertTrue((m5 > -1).all())
        self.assertTrue(m5.replace([np.inf, -np.inf], np.nan).notna().all())

    def test_constant_price_rsi(self):
        """恒定价格时 RSI 应为 50"""
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        rows = []
        for d in dates:
            rows.append({"date": d, "instrument": "SH600000",
                          "$close": 10.0, "$volume": 1_000_000})
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index(["date", "instrument"])
        df.index.names = ["datetime", "instrument"]
        result = compute_factors(df)
        # RSI on constant series → 50 (no gains or losses)
        rsi_vals = result["rsi_14"].dropna()
        if len(rsi_vals) > 0:
            self.assertAlmostEqual(rsi_vals.iloc[0], 50.0, places=5)


class TestComputeIC(unittest.TestCase):
    """测试 compute_ic()"""

    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        instruments = [f"SH{i:06d}" for i in range(100, 120)]
        self.df = _make_price_df(instruments, dates)
        np.random.seed(42)
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        self.factors_df = pd.DataFrame({
            "momentum_5d": np.random.randn(len(idx)),
            "rsi_14": np.random.randn(len(idx)),
        }, index=idx)

    def test_returns_dataframe(self):
        result = compute_ic(self.factors_df, self.df)
        self.assertIsInstance(result, pd.DataFrame)

    def test_columns_when_nonempty(self):
        result = compute_ic(self.factors_df, self.df)
        if not result.empty:
            self.assertIn("factor_id", result.columns)
            self.assertIn("IC_5d", result.columns)

    def test_empty_price_data(self):
        empty_df = pd.DataFrame(columns=["$close", "$volume"])
        empty_df.index = pd.MultiIndex.from_tuples([], names=["datetime", "instrument"])
        result = compute_ic(self.factors_df, empty_df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)


class TestSynthesizeScore(unittest.TestCase):
    """测试 synthesize_score()"""

    def _make_series(self, values, date="2024-01-01"):
        insts = [f"SH{i:06d}" for i in range(100, 100 + len(values))]
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp(date), inst) for inst in insts],
            names=["datetime", "instrument"])
        return pd.Series(values, index=idx)

    def test_basic_synthesis(self):
        data = {
            "factor_a": self._make_series([1.0, 2.0, 3.0]),
            "factor_b": self._make_series([3.0, 1.0, 2.0]),
        }
        result = synthesize_score(data)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertIn("composite_score", result.columns)
        self.assertIn("rank", result.columns)
        self.assertEqual(len(result), 3)

    def test_empty_input(self):
        result = synthesize_score({})
        self.assertIsNone(result)

    def test_std_zero_no_error(self):
        """所有值相同时 std=0，不应报错"""
        idx = pd.MultiIndex.from_tuples(
            [("2024-01-01", f"SH{i:06d}") for i in range(100, 103)],
            names=["datetime", "instrument"])
        data = {"factor_a": pd.Series([5.0, 5.0, 5.0], index=idx)}
        result = synthesize_score(data)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 3)


class TestFactorNamesConstant(unittest.TestCase):
    """测试 FACTOR_NAMES 常量"""

    def test_contains_expected_factors(self):
        expected = {
            "momentum_5d", "momentum_10d", "momentum_20d",
            "reversal_5d", "volatility_20d", "rsi_14",
            "macd", "bollinger_pos", "volume_ratio",
        }
        self.assertEqual(set(FACTOR_NAMES), expected)
        self.assertEqual(len(FACTOR_NAMES), 9)


if __name__ == "__main__":
    unittest.main()
