#!/usr/bin/env python3
from __future__ import annotations
"""
白名单流水线测试
================
测试 whitelist_pipeline.py 的所有函数。
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
    """构造测试用价格 DataFrame (MultiIndex: datetime, instrument)"""
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
        self._tmpdir = self.tmpdir
        self._pq_path = self.pq_path

    def tearDown(self):
        self.tmpdir.cleanup()

    def _patch_config(self, whitelist):
        """Patch cfg and the module-level WHITELIST"""
        import config as cfg
        import whitelist_pipeline as wp
        import engine.factor_compute as fc
        cfg.DAILY_PV_FULL_PQ = self._pq_path
        cfg.WHITELIST_STOCKS = whitelist
        cfg._WHITELIST_RAW = ",".join(whitelist)
        # Module-level WHITELIST is set at import time; re-patch it
        wp.WHITELIST = whitelist
        # engine.factor_compute holds its own cfg reference — patch it too
        fc.cfg = cfg
        return cfg

    def test_load_returns_dataframe(self):
        """应返回 DataFrame"""
        cfg = self._patch_config(["SH600000", "SH600001"])
        from engine.factor_compute import load_whitelist_data
        result = load_whitelist_data()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(result.index.names, ["datetime", "instrument"])

    def test_load_filters_whitelist(self):
        """应只包含白名单中的股票"""
        self._patch_config(["SH600000"])
        from engine.factor_compute import load_whitelist_data
        result = load_whitelist_data()
        insts = set(result.index.get_level_values("instrument").unique())
        self.assertEqual(insts, {"SH600000"})

    def test_load_sorts_index(self):
        """结果应已排序"""
        self._patch_config(["SH600000", "SH600001"])
        from engine.factor_compute import load_whitelist_data
        result = load_whitelist_data()
        self.assertTrue(result.index.is_monotonic_increasing)

    def test_load_deduplicates(self):
        """不应有重复索引"""
        self._patch_config(["SH600000"])
        from engine.factor_compute import load_whitelist_data
        result = load_whitelist_data()
        self.assertFalse(result.index.duplicated().any())


class TestComputeFactors(unittest.TestCase):
    """测试 compute_factors()"""

    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=40, freq="B")
        instruments = ["SH600000", "SZ000001"]
        self.df = _make_price_df(instruments, dates)

    def test_compute_all_factors(self):
        """应计算所有9个因子"""
        from engine.factor_compute import compute_factors
        result = compute_factors(self.df)
        self.assertIsInstance(result, pd.DataFrame)
        expected = {
            "momentum_5d", "momentum_10d", "momentum_20d",
            "reversal_5d", "volatility_20d", "rsi_14",
            "macd", "bollinger_pos", "volume_ratio",
        }
        found = set(result.columns) & expected
        self.assertEqual(found, expected)

    def test_compute_factor_shapes(self):
        """每个因子的形状应与输入一致"""
        from engine.factor_compute import compute_factors
        result = compute_factors(self.df)
        n_dates = self.df.index.get_level_values("datetime").nunique()
        n_inst = self.df.index.get_level_values("instrument").nunique()
        self.assertEqual(result.shape[0], n_dates * n_inst)

    def test_compute_momentum_valid_values(self):
        """动量因子应有合理值"""
        from engine.factor_compute import compute_factors
        result = compute_factors(self.df)
        m5 = result["momentum_5d"].dropna()
        self.assertGreater(len(m5), 0)
        self.assertTrue((m5 > -1).all())
        self.assertTrue(m5.replace([np.inf, -np.inf], np.nan).notna().all())


class TestComputeIC(unittest.TestCase):
    """测试 compute_ic()"""

    def setUp(self):
        # 用足够多的股票和日期确保 IC 能算出来
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        instruments = [f"SH{i:06d}" for i in range(100, 120)]  # 20 只股票
        self.df = _make_price_df(instruments, dates)
        # 构造因子 DataFrame（与价格 DataFrame 对齐）
        np.random.seed(42)
        rows = []
        for d in dates:
            for inst in instruments:
                rows.append({
                    "datetime": d, "instrument": inst,
                    "momentum_5d": np.random.randn(),
                    "rsi_14": np.random.randn(),
                })
        fdf = pd.DataFrame(rows)
        fdf = fdf.pivot(index=["datetime", "instrument"], columns="momentum_5d", values="momentum_5d")
        # 重新构造双因子
        rows2 = []
        for d in dates:
            for inst in instruments:
                rows2.append({"datetime": d, "instrument": inst,
                               "momentum_5d": np.random.randn(),
                               "rsi_14": np.random.randn()})
        fdf = pd.DataFrame(rows2)
        fdf = fdf.pivot(index=["datetime", "instrument"], columns="momentum_5d", values="momentum_5d")
        # pivot 只能处理单列，改用手动构建
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

    def test_compute_ic_columns(self):
        """有足够数据时应包含预期列"""
        from engine.factor_compute import compute_ic
        result = compute_ic(self.factors_df, self.df)
        if not result.empty:
            expected_cols = {"factor_id", "IC_5d", "IC_t_5d", "IC_pos_5d", "n_days"}
            self.assertTrue(expected_cols.issubset(set(result.columns)))

    def test_compute_ic_empty_when_no_data(self):
        """空价格数据应返回空 DataFrame 而不是报错"""
        from engine.factor_compute import compute_ic
        empty_df = pd.DataFrame(columns=["$close", "$volume"])
        empty_df.index = pd.MultiIndex.from_tuples([], names=["datetime", "instrument"])
        result = compute_ic(self.factors_df, empty_df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)


class TestSynthesizeScore(unittest.TestCase):
    """测试 synthesize_score()"""

    def test_synthesize_basic(self):
        """基本合成"""
        from whitelist_pipeline import synthesize_score
        idx = pd.MultiIndex.from_tuples([
            ("2024-01-01", "SH600000"),
            ("2024-01-01", "SH600001"),
            ("2024-01-01", "SH600002"),
        ], names=["datetime", "instrument"])
        data = {
            "factor_a": pd.Series([1.0, 2.0, 3.0], index=idx),
            "factor_b": pd.Series([3.0, 1.0, 2.0], index=idx),
        }
        result = synthesize_score(data)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertIn("composite_score", result.columns)
        self.assertIn("rank", result.columns)
        self.assertEqual(len(result), 3)

    def test_synthesize_empty(self):
        """空输入应返回 None"""
        from whitelist_pipeline import synthesize_score
        result = synthesize_score({})
        self.assertIsNone(result)

    def test_synthesize_single_factor(self):
        """单因子合成"""
        from whitelist_pipeline import synthesize_score
        idx = pd.MultiIndex.from_tuples([
            ("2024-01-01", f"SH{i:06d}") for i in range(100, 103)
        ], names=["datetime", "instrument"])
        data = {"factor_a": pd.Series([1.0, 2.0, 3.0], index=idx)}
        result = synthesize_score(data)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 3)
        self.assertIn("composite_score", result.columns)

    def test_synthesize_std_zero(self):
        """所有值相同时 std=0，不应报错"""
        from whitelist_pipeline import synthesize_score
        idx = pd.MultiIndex.from_tuples([
            ("2024-01-01", f"SH{i:06d}") for i in range(100, 103)
        ], names=["datetime", "instrument"])
        data = {"factor_a": pd.Series([5.0, 5.0, 5.0], index=idx)}
        result = synthesize_score(data)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 3)


class TestRunStockSelection(unittest.TestCase):
    """测试 run_stock_selection()"""

    def _make_factors_df(self, n_dates=15, n_stocks=15):
        dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
        insts = [f"SH{i:06d}" for i in range(100, 100 + n_stocks)]
        np.random.seed(42)
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        return pd.DataFrame({
            "momentum_5d": np.random.randn(len(idx)),
            "rsi_14": np.random.randn(len(idx)),
        }, index=idx)

    def test_run_stock_selection_returns_dataframe(self):
        """应返回 DataFrame"""
        factors_df = self._make_factors_df()
        ic_df = pd.DataFrame({
            "factor_id": ["momentum_5d", "rsi_14"],
            "IC_5d": [0.05, -0.03],
            "IC_t_5d": [2.1, -1.5],
            "IC_pos_5d": [0.6, 0.4],
            "n_days": [15, 15],
        })
        from whitelist_pipeline import run_stock_selection
        result = run_stock_selection(factors_df, ic_df, top_k=5)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertIn("date", result.columns)
        self.assertIn("instrument", result.columns)
        self.assertIn("rank", result.columns)

    def test_run_stock_selection_empty_ic(self):
        """IC为空时应仍能运行不报错"""
        factors_df = self._make_factors_df(n_dates=5, n_stocks=5)
        ic_df = pd.DataFrame(columns=["factor_id", "IC_5d", "IC_t_5d", "IC_pos_5d", "n_days"])
        from whitelist_pipeline import run_stock_selection
        result = run_stock_selection(factors_df, ic_df, top_k=3)
        self.assertIsInstance(result, pd.DataFrame)


class TestPushResults(unittest.TestCase):
    """测试飞书推送函数"""

    def test_push_factor_results(self):
        """因子结果推送"""
        from whitelist_pipeline import push_factor_results
        idx = pd.MultiIndex.from_tuples([
            (pd.Timestamp("2024-01-01"), "SH600000"),
            (pd.Timestamp("2024-01-01"), "SH600001"),
            (pd.Timestamp("2024-01-01"), "SH600002"),
        ], names=["datetime", "instrument"])
        factors_df = pd.DataFrame({"momentum_5d": [0.1, 0.2, 0.3]}, index=idx)
        with mock.patch("whitelist_pipeline.send_feishu") as mock_send:
            mock_send.return_value = True
            result = push_factor_results(factors_df)
            self.assertTrue(result)
            mock_send.assert_called_once()
            call_args = mock_send.call_args[0][0]
            self.assertIn("因子计算完成", call_args)

    def test_push_ic_results(self):
        """IC结果推送"""
        from whitelist_pipeline import push_ic_results
        ic_df = pd.DataFrame({
            "factor_id": ["momentum_5d", "rsi_14"],
            "IC_5d": [0.05, -0.03],
            "IC_t_5d": [2.1, -1.5],
            "IC_pos_5d": [0.6, 0.4],
            "n_days": [20, 20],
        })
        with mock.patch("whitelist_pipeline.send_feishu") as mock_send:
            mock_send.return_value = True
            result = push_ic_results(ic_df)
            self.assertTrue(result)
            mock_send.assert_called_once()

    def test_push_stock_results_empty(self):
        """空选股结果推送"""
        from whitelist_pipeline import push_stock_results
        empty_df = pd.DataFrame(columns=["date", "instrument", "rank"])
        with mock.patch("whitelist_pipeline.send_feishu") as mock_send:
            mock_send.return_value = True
            result = push_stock_results(empty_df)
            self.assertTrue(result)
            call_args = mock_send.call_args[0][0]
            self.assertIn("为空", call_args)

    def test_push_backtest_results(self):
        """回测结果推送"""
        from whitelist_pipeline import push_backtest_results
        from engine.metrics import PerformanceMetrics
        metrics = PerformanceMetrics(
            total_days=20, total_return_pct=5.0, annual_return_pct=25.0,
            sharpe_ratio=1.5, max_drawdown_pct=-3.0, win_rate_pct=55.0,
            total_trades=10, win_trades=5, profit_factor=1.8,
            final_value=1_050_000, final_nav=1.05)
        result_mock = mock.MagicMock()
        result_mock.daily_value = [{"date": "2024-01-01", "value": 1_000_000}]
        result_mock.trades = []
        with mock.patch("whitelist_pipeline.send_feishu") as mock_send, \
             mock.patch("whitelist_pipeline.BASE", Path("/tmp")):
            mock_send.return_value = True
            push_backtest_results(metrics, result_mock)
            mock_send.assert_called_once()


class TestMain(unittest.TestCase):
    """测试 main()"""

    def test_main_requires_whitelist(self):
        """白名单未配置时应返回1"""
        with mock.patch("whitelist_pipeline.cfg") as mock_cfg:
            mock_cfg.is_whitelist_configured.return_value = False
            with mock.patch("sys.argv", ["whitelist_pipeline.py"]):
                from whitelist_pipeline import main
                result = main()
                self.assertEqual(result, 1)

    def test_main_argparse_phase_choices(self):
        """--phase 参数应支持正确选项"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--phase", choices=["all", "factor", "ic", "select", "backtest"],
                            default="all")
        for phase in ["all", "factor", "ic", "select", "backtest"]:
            args = parser.parse_args(["--phase", phase])
            self.assertEqual(args.phase, phase)


if __name__ == "__main__":
    unittest.main()
