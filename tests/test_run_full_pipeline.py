#!/usr/bin/env python3
from __future__ import annotations
"""
run_full_pipeline.py 测试
=========================
测试完整流水线的各个 phase 函数。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd


class TestPhaseRecomputeFactors(unittest.TestCase):
    """测试 phase_recompute_factors()"""

    def test_phase_recompute_returns_true(self):
        with mock.patch("run_full_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            with mock.patch("run_full_pipeline.check_data_freshness") as mock_fresh:
                mock_fresh.return_value = {
                    "price_cutoff": pd.Timestamp("2024-01-01"),
                    "factor_cutoff": pd.Timestamp("2024-01-01"),
                    "freshness": "fresh",
                }
                from run_full_pipeline import phase_recompute_factors
                result = phase_recompute_factors()
                self.assertTrue(result)

    def test_phase_recompute_subprocess_failure(self):
        with mock.patch("run_full_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1)
            with mock.patch("run_full_pipeline.check_data_freshness") as mock_fresh:
                mock_fresh.return_value = {
                    "price_cutoff": None, "factor_cutoff": None, "freshness": "unknown"
                }
                from run_full_pipeline import phase_recompute_factors
                result = phase_recompute_factors()
                self.assertTrue(result)

    def test_phase_recompute_dry_run(self):
        with mock.patch("run_full_pipeline.subprocess.run") as mock_run:
            with mock.patch("run_full_pipeline.check_data_freshness") as mock_fresh:
                mock_fresh.return_value = {
                    "price_cutoff": pd.Timestamp("2024-01-01"),
                    "factor_cutoff": pd.Timestamp("2024-01-01"),
                    "freshness": "fresh",
                }
                from run_full_pipeline import phase_recompute_factors
                result = phase_recompute_factors(dry_run=True)
                self.assertTrue(result)
                mock_run.assert_not_called()


class TestPhaseIcAnalysis(unittest.TestCase):
    """测试 phase_ic_analysis()"""

    def test_phase_ic_analysis_returns_results(self):
        with mock.patch("run_full_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            with mock.patch("run_full_pipeline.check_data_freshness") as mock_fresh:
                mock_fresh.return_value = {
                    "price_cutoff": pd.Timestamp("2024-01-01"),
                    "factor_cutoff": pd.Timestamp("2024-01-01"),
                    "freshness": "fresh",
                }
                tmpdir = tempfile.TemporaryDirectory()
                ic_csv = Path(tmpdir.name) / "ic_scan_results_new.csv"
                ic_csv.write_text("factor_id,IC_5d\nmomentum_5d,0.05\n")
                with mock.patch("run_full_pipeline.cfg") as mock_cfg:
                    mock_cfg.PROJECT_ROOT = Path(tmpdir.name)
                    from run_full_pipeline import phase_ic_analysis
                    result = phase_ic_analysis()
                    self.assertIsInstance(result, pd.DataFrame)
                    self.assertEqual(len(result), 1)
                tmpdir.cleanup()

    def test_phase_ic_analysis_no_csv(self):
        with mock.patch("run_full_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            with mock.patch("run_full_pipeline.check_data_freshness") as mock_fresh:
                mock_fresh.return_value = {
                    "price_cutoff": None, "factor_cutoff": None, "freshness": "unknown"
                }
                tmpdir = tempfile.TemporaryDirectory()
                with mock.patch("run_full_pipeline.cfg") as mock_cfg:
                    mock_cfg.PROJECT_ROOT = Path(tmpdir.name)
                    from run_full_pipeline import phase_ic_analysis
                    result = phase_ic_analysis()
                    self.assertTrue(result.empty)
                tmpdir.cleanup()


class TestPhaseStockSelection(unittest.TestCase):
    """测试 phase_stock_selection()"""

    def test_phase_stock_selection_returns_results(self):
        with mock.patch("run_full_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            tmpdir = tempfile.TemporaryDirectory()
            stocks_csv = Path(tmpdir.name) / "top10_stocks_new.csv"
            stocks_csv.write_text("instrument,date,rank\nSH600000,2024-01-01,1\n")
            with mock.patch("run_full_pipeline.cfg") as mock_cfg:
                mock_cfg.PROJECT_ROOT = Path(tmpdir.name)
                from run_full_pipeline import phase_stock_selection
                result = phase_stock_selection(pd.DataFrame())
                self.assertIsInstance(result, pd.DataFrame)
            tmpdir.cleanup()

    def test_phase_stock_selection_no_csv(self):
        with mock.patch("run_full_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            tmpdir = tempfile.TemporaryDirectory()
            with mock.patch("run_full_pipeline.cfg") as mock_cfg:
                mock_cfg.PROJECT_ROOT = Path(tmpdir.name)
                from run_full_pipeline import phase_stock_selection
                result = phase_stock_selection(pd.DataFrame())
                self.assertTrue(result.empty)
            tmpdir.cleanup()


class TestPhaseBacktest(unittest.TestCase):
    """测试 phase_backtest()"""

    def test_phase_backtest_whitelist_mode(self):
        with mock.patch("run_full_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            tmpdir = tempfile.TemporaryDirectory()
            nav_csv = Path(tmpdir.name) / "whitelist_backtest_nav.csv"
            nav_csv.write_text("date,value\n2024-01-01,1000000\n2024-01-02,1050000\n")
            trades_csv = Path(tmpdir.name) / "whitelist_backtest_trades.csv"
            trades_csv.write_text("date,action,stock,shares,price,value,pnl_pct,reason\n")
            with mock.patch("run_full_pipeline.cfg") as mock_cfg:
                mock_cfg.is_whitelist_configured.return_value = True
                mock_cfg.PROJECT_ROOT = Path(tmpdir.name)
                from run_full_pipeline import phase_backtest
                result = phase_backtest(whitelist=["SH600000"])
                self.assertIn("total_return", result)
                self.assertAlmostEqual(result["total_return"], 5.0, places=1)
            tmpdir.cleanup()

    def test_phase_backtest_normal_mode(self):
        with mock.patch("run_full_pipeline.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            tmpdir = tempfile.TemporaryDirectory()
            nav_csv = Path(tmpdir.name) / "backtest_nav.csv"
            nav_csv.write_text("date,value\n2024-01-01,1000000\n2024-01-02,1100000\n")
            trades_csv = Path(tmpdir.name) / "backtest_trades.csv"
            trades_csv.write_text("date,action,stock,shares,price,value,pnl_pct,reason\n")
            with mock.patch("run_full_pipeline.cfg") as mock_cfg:
                mock_cfg.is_whitelist_configured.return_value = False
                mock_cfg.PROJECT_ROOT = Path(tmpdir.name)
                from run_full_pipeline import phase_backtest
                result = phase_backtest()
                self.assertIn("total_return", result)
                self.assertAlmostEqual(result["total_return"], 10.0, places=1)
            tmpdir.cleanup()


class TestPhasePerformanceEvaluation(unittest.TestCase):
    """测试 phase_performance_evaluation()"""

    def test_eval_with_nav(self):
        tmpdir = tempfile.TemporaryDirectory()
        nav_csv = Path(tmpdir.name) / "backtest_nav.csv"
        nav_csv.write_text("date,value\n2024-01-01,1000000\n2024-01-02,1100000\n")
        trades_csv = Path(tmpdir.name) / "backtest_trades.csv"
        trades_csv.write_text("date,action,stock,shares,price,value,pnl_pct,reason\n")
        with mock.patch("run_full_pipeline.cfg") as mock_cfg:
            mock_cfg.PROJECT_ROOT = Path(tmpdir.name)
            mock_cfg.BACKTEST_INITIAL_CAPITAL = 1_000_000
            from run_full_pipeline import phase_performance_evaluation
            result = phase_performance_evaluation({"total_return": 10.0})
            self.assertIsInstance(result, dict)
            self.assertIn("total_return", result)
        tmpdir.cleanup()

    def test_eval_missing_nav(self):
        tmpdir = tempfile.TemporaryDirectory()
        with mock.patch("run_full_pipeline.cfg") as mock_cfg:
            mock_cfg.PROJECT_ROOT = Path(tmpdir.name)
            from run_full_pipeline import phase_performance_evaluation
            result = phase_performance_evaluation({})
            self.assertEqual(result, {})
        tmpdir.cleanup()


class TestMain(unittest.TestCase):
    """测试 main()"""

    def test_main_requires_whitelist_when_flag_set(self):
        with mock.patch("run_full_pipeline.cfg") as mock_cfg:
            mock_cfg.is_whitelist_configured.return_value = False
            with mock.patch("sys.argv", ["run_full_pipeline.py", "--whitelist"]):
                from run_full_pipeline import main
                result = main()
                self.assertEqual(result, 1)

    def test_main_argparse(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--phase", choices=["all", "recompute", "ic", "select", "backtest", "evaluate", "push"],
                            default="all")
        parser.add_argument("--top-n", type=int, default=10)
        parser.add_argument("--feishu-url", default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--whitelist", action="store_true")
        args = parser.parse_args(["--phase", "ic", "--top-n", "5", "--dry-run"])
        self.assertEqual(args.phase, "ic")
        self.assertEqual(args.top_n, 5)
        self.assertTrue(args.dry_run)
        self.assertFalse(args.whitelist)


if __name__ == "__main__":
    unittest.main()
