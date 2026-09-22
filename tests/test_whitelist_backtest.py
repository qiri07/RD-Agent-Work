#!/usr/bin/env python3
from __future__ import annotations
"""
白名单回测脚本测试
==================
测试 whitelist_backtest.py 的所有函数。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd


def _make_price_df(instruments, dates):
    rows = []
    np.random.seed(42)
    for inst in instruments:
        price = 10.0
        for d in dates:
            price *= 1 + np.random.randn() * 0.01
            rows.append({
                "date": d, "instrument": inst,
                "$close": price, "$volume": int(1_000_000 * (1 + np.random.randn() * 0.1)),
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
        self._tmpdir = self.tmpdir
        self._pq_path = self.pq_path

    def tearDown(self):
        self.tmpdir.cleanup()

    def _patch_config(self, whitelist):
        import config as cfg
        import whitelist_backtest as wb
        import engine.factor_compute as fc
        cfg.DAILY_PV_FULL_PQ = self._pq_path
        cfg.WHITELIST_STOCKS = whitelist
        cfg._WHITELIST_RAW = ",".join(whitelist)
        wb.WHITELIST = whitelist
        # engine.factor_compute holds its own cfg reference — patch it too
        fc.cfg = cfg
        return cfg

    def test_load_whitelist_data(self):
        """应返回过滤后的 DataFrame"""
        self._patch_config(["SH600000"])
        from engine.factor_compute import load_whitelist_data
        result = load_whitelist_data()
        self.assertIsInstance(result, pd.DataFrame)
        insts = set(result.index.get_level_values("instrument").unique())
        self.assertEqual(insts, {"SH600000"})

    def test_load_whitelist_data_dedup(self):
        """重复索引应去重"""
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        rows = []
        for d in dates:
            rows.append({"date": d, "instrument": "SH600000", "$close": 10.0, "$volume": 1_000_000})
            rows.append({"date": d, "instrument": "SH600000", "$close": 11.0, "$volume": 2_000_000})
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index(["date", "instrument"])
        df.to_parquet(self._pq_path)
        self._patch_config(["SH600000"])
        from engine.factor_compute import load_whitelist_data
        result = load_whitelist_data()
        self.assertFalse(result.index.duplicated().any())


class TestComputeFactors(unittest.TestCase):
    """测试 compute_factors()"""

    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        instruments = ["SH600000", "SZ000001"]
        self.df = _make_price_df(instruments, dates)

    def test_compute_factors_returns_dataframe(self):
        """应返回 DataFrame"""
        from engine.factor_compute import compute_factors
        result = compute_factors(self.df)
        self.assertIsInstance(result, pd.DataFrame)

    def test_compute_factors_has_all_factors(self):
        """应包含所有9个因子"""
        from engine.factor_compute import compute_factors
        result = compute_factors(self.df)
        expected = {
            "momentum_5d", "momentum_10d", "momentum_20d",
            "reversal_5d", "volatility_20d", "rsi_14",
            "macd", "bollinger_pos", "volume_ratio",
        }
        self.assertTrue(expected.issubset(set(result.columns)))

    def test_compute_factors_valid_momentum(self):
        """动量因子值应在合理范围"""
        from engine.factor_compute import compute_factors
        result = compute_factors(self.df)
        m5 = result["momentum_5d"].dropna()
        self.assertGreater(len(m5), 0)
        self.assertTrue((m5 > -1).all())


class TestComputeIC(unittest.TestCase):
    """测试 compute_ic()"""

    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        instruments = [f"SH{i:06d}" for i in range(100, 120)]  # 20 stocks
        self.df = _make_price_df(instruments, dates)
        np.random.seed(42)
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        self.factors_df = pd.DataFrame({
            "momentum_5d": np.random.randn(len(idx)),
            "rsi_14": np.random.randn(len(idx)),
        }, index=idx)

    def test_compute_ic_returns_dataframe(self):
        """应返回 DataFrame"""
        from engine.factor_compute import compute_ic
        result = compute_ic(self.factors_df, self.df)
        self.assertIsInstance(result, pd.DataFrame)

    def test_compute_ic_empty_price_data(self):
        """空价格数据应返回空 DataFrame"""
        from engine.factor_compute import compute_ic
        empty_df = pd.DataFrame(columns=["$close", "$volume"])
        empty_df.index = pd.MultiIndex.from_tuples([], names=["datetime", "instrument"])
        result = compute_ic(self.factors_df, empty_df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)


class TestMain(unittest.TestCase):
    """测试 main()"""

    def test_main_requires_whitelist(self):
        """白名单未配置应返回1"""
        with mock.patch("whitelist_backtest.cfg") as mock_cfg:
            mock_cfg.is_whitelist_configured.return_value = False
            from whitelist_backtest import main
            result = main()
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
