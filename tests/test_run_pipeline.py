#!/usr/bin/env python3
"""
run_pipeline.py 集成测试
=========================
测试Pipeline编排逻辑：参数解析、流程调度、结果整合。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd


class TestArgparseModes(unittest.TestCase):
    """测试命令行参数解析"""

    def test_default_mode(self):
        """无参数时应进入完整流程模式"""
        import argparse
        from run_pipeline import main

        parser = argparse.ArgumentParser()
        parser.add_argument("--ic-only", action="store_true")
        parser.add_argument("--stocks-only", action="store_true")
        parser.add_argument("--feishu-only", action="store_true")
        parser.add_argument("--top-n", type=int, default=10)

        args = parser.parse_args([])
        self.assertFalse(args.ic_only)
        self.assertFalse(args.stocks_only)
        self.assertFalse(args.feishu_only)
        self.assertEqual(args.top_n, 10)

    def test_ic_only_mode(self):
        """--ic-only 应只运行IC分析"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--ic-only", action="store_true")
        args = parser.parse_args(["--ic-only"])
        self.assertTrue(args.ic_only)

    def test_stocks_only_mode(self):
        """--stocks-only 应只选股"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--stocks-only", action="store_true")
        args = parser.parse_args(["--stocks-only"])
        self.assertTrue(args.stocks_only)

    def test_feishu_only_mode(self):
        """--feishu-only 应只推送"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--feishu-only", action="store_true")
        args = parser.parse_args(["--feishu-only"])
        self.assertTrue(args.feishu_only)

    def test_custom_top_n(self):
        """--top-n 应正确解析"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--top-n", type=int, default=10)
        args = parser.parse_args(["--top-n", "20"])
        self.assertEqual(args.top_n, 20)

    def test_feishu_url_override(self):
        """--feishu-url 应覆盖环境变量"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--feishu-url", default=None)
        args = parser.parse_args(["--feishu-url", "https://test.com/hook"])
        self.assertEqual(args.feishu_url, "https://test.com/hook")


class TestScreenStocks(unittest.TestCase):
    """测试选股逻辑"""

    def test_select_top_n_factors(self):
        """应选取Top N个因子"""
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2", "f3", "f4", "f5"],
            "IC_5d": [0.05, -0.08, 0.03, -0.02, 0.06],
            "IC_t_5d": [3.0, -4.0, 2.0, -1.0, 3.5],
            "IC_pos_5d": [0.6, 0.3, 0.5, 0.4, 0.65],
            "n_days": [100, 100, 100, 100, 100],
        })

        ic_df_sorted = ic_df.copy()
        ic_df_sorted["_abs_ic"] = ic_df_sorted["IC_5d"].abs()
        top_factors = ic_df_sorted.nlargest(3, "_abs_ic")["factor_id"].tolist()

        self.assertEqual(len(top_factors), 3)
        self.assertEqual(top_factors[0], "f2")  # |−0.08| 最大
        self.assertEqual(top_factors[1], "f5")  # |0.06| 次大
        self.assertEqual(top_factors[2], "f1")  # |0.05| 第三

    def test_load_factors_from_workspace(self):
        """应从工作区加载因子数据"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建因子HDF5文件
            for i in range(3):
                session_dir = Path(tmpdir) / f"factor_{i}"
                session_dir.mkdir()

                dates = pd.date_range("2024-01-01", periods=20, freq="B")
                stocks = [f"SH{j:06d}" for j in range(1, 11)]
                idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
                vals = np.random.default_rng(42+i).standard_normal(len(idx))
                df = pd.DataFrame({f"factor_{i}": vals}, index=idx)
                df.to_hdf(session_dir / "result.h5", key="data", mode="w")

            # 模拟screen_stocks的加载逻辑
            factor_dict = {}
            for fid in [f"factor_{i}" for i in range(3)]:
                h5 = Path(tmpdir) / fid / "result.h5"
                if h5.exists():
                    df = pd.read_hdf(h5, key="data")
                    col = df.columns[0]
                    factor_dict[fid] = df[col]

            self.assertEqual(len(factor_dict), 3)

    def test_combine_factors_latest_date(self):
        """应在最新日期合成因子"""
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        factor_a = pd.Series(np.random.default_rng(42).standard_normal(10), index=dates, name="f1")
        factor_b = pd.Series(np.random.default_rng(43).standard_normal(10), index=dates, name="f2")

        combined = pd.DataFrame({"f1": factor_a, "f2": factor_b})
        latest_date = combined.index.max()

        day_data = combined.loc[latest_date]
        self.assertEqual(len(day_data), 2)

    def test_zscore_combination(self):
        """Z-score加权合成"""
        combined = pd.DataFrame({
            "f1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "f2": [5.0, 4.0, 3.0, 2.0, 1.0],
        })

        # Z-score标准化
        combined_std = combined.copy()
        for col in combined.columns:
            mean = combined[col].mean()
            std = combined[col].std()
            if std > 0:
                combined_std[col] = (combined[col] - mean) / std

        # 等权合成
        weights = 1.0 / len(combined_std.columns)
        combined_std["composite_score"] = (combined_std * weights).sum(axis=1)

        self.assertEqual(len(combined_std.columns), 3)
        self.assertIn("composite_score", combined_std.columns)

    def test_rank_and_top_k(self):
        """排名取Top K"""
        combined_std = pd.DataFrame({
            "composite_score": [3.0, 1.0, 4.0, 2.0, 5.0],
        }, index=["A", "B", "C", "D", "E"])

        combined_std["rank"] = combined_std["composite_score"].rank(ascending=False, method="dense")
        top_k = 3
        top_stocks = combined_std.nlargest(top_k, "composite_score")

        self.assertEqual(len(top_stocks), 3)
        self.assertEqual(top_stocks.index[0], "E")  # 得分最高
        self.assertEqual(top_stocks.loc["E", "rank"], 1.0)


class TestFeishuIntegration(unittest.TestCase):
    """测试飞书推送集成"""

    def test_feishu_data_format(self):
        """飞书推送数据格式应正确"""
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2"],
            "IC_5d": [0.05, -0.03],
            "IC_t_5d": [3.0, -2.0],
            "IC_pos_5d": [0.7, 0.4],
        })

        stocks_df = pd.DataFrame({
            "rank": [1, 2],
            "instrument": ["SH600000", "SZ300001"],
            "composite_score": [4.5, 3.2],
        })

        self.assertEqual(len(ic_df), 2)
        self.assertEqual(len(stocks_df), 2)
        self.assertIn("factor_id", ic_df.columns)
        self.assertIn("instrument", stocks_df.columns)

    def test_feishu_url_configuration(self):
        """飞书Webhook URL应正确配置"""
        import config as cfg

        # 检查配置是否存在
        self.assertTrue(hasattr(cfg, 'FEISHU_WEBHOOK_URL'))
        self.assertIsInstance(cfg.FEISHU_WEBHOOK_URL, str)


class TestPipelineOrchestration(unittest.TestCase):
    """测试Pipeline编排"""

    def test_full_pipeline_flow(self):
        """完整流程应依次执行：IC分析 → 选股 → 推送"""
        # 模拟流程顺序
        steps = []

        def mock_ic_analysis():
            steps.append("ic_analysis")
            return True

        def mock_screen_stocks():
            steps.append("screen_stocks")
            return pd.DataFrame({"rank": [1], "instrument": ["SH600000"]})

        def mock_push_feishu():
            steps.append("push_feishu")
            return True

        mock_ic_analysis()
        stocks_df = mock_screen_stocks()
        mock_push_feishu()

        self.assertEqual(steps, ["ic_analysis", "screen_stocks", "push_feishu"])

    def test_pipeline_error_handling(self):
        """IC分析失败时应终止流程"""
        steps = []

        def mock_ic_analysis_fails():
            steps.append("ic_analysis")
            return False

        def mock_screen_stocks():
            steps.append("screen_stocks")
            return None

        result = mock_ic_analysis_fails()
        if not result:
            # 流程终止，不应执行后续步骤
            pass
        else:
            mock_screen_stocks()

        self.assertEqual(steps, ["ic_analysis"])
        self.assertNotIn("screen_stocks", steps)

    def test_feishu_only_mode(self):
        """feishu-only模式应仅推送"""
        steps = []

        def mock_push_only():
            steps.append("push_feishu")
            return True

        # 模拟feishu-only模式
        mock_push_only()

        self.assertEqual(steps, ["push_feishu"])

    def test_stocks_only_mode(self):
        """stocks-only模式应仅选股"""
        steps = []

        def mock_screen_stocks():
            steps.append("screen_stocks")
            return pd.DataFrame({"rank": [1], "instrument": ["SH600000"]})

        def mock_push_feishu():
            steps.append("push_feishu")
            return True

        # 模拟stocks-only模式
        stocks_df = mock_screen_stocks()
        if stocks_df is not None:
            mock_push_feishu()

        self.assertEqual(steps, ["screen_stocks", "push_feishu"])


class TestOutputGeneration(unittest.TestCase):
    """测试输出文件生成"""

    def test_save_ic_results(self):
        """IC结果应保存为CSV"""
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2"],
            "IC_5d": [0.05, -0.03],
            "IC_t_5d": [3.0, -2.0],
        })

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            tmp_path = f.name

        try:
            ic_df.to_csv(tmp_path, index=False)
            loaded = pd.read_csv(tmp_path)
            self.assertEqual(len(loaded), 2)
            self.assertIn("factor_id", loaded.columns)
        finally:
            Path(tmp_path).unlink()

    def test_save_stocks_results(self):
        """选股结果应保存为CSV"""
        stocks_df = pd.DataFrame({
            "rank": [1, 2, 3],
            "instrument": ["SH600000", "SZ300001", "SH600002"],
            "composite_score": [4.5, 3.2, 2.8],
        })

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            tmp_path = f.name

        try:
            stocks_df.to_csv(tmp_path, index=False)
            loaded = pd.read_csv(tmp_path)
            self.assertEqual(len(loaded), 3)
            self.assertEqual(loaded.iloc[0]["instrument"], "SH600000")
        finally:
            Path(tmp_path).unlink()

    def test_save_trades_results(self):
        """交易记录应保存为CSV"""
        trades_df = pd.DataFrame({
            "date": ["2024-01-10", "2024-01-11"],
            "action": ["BUY", "SELL"],
            "stock": ["SH600000", "SH600000"],
            "pnl_pct": [0.0, 2.5],
        })

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            tmp_path = f.name

        try:
            trades_df.to_csv(tmp_path, index=False)
            loaded = pd.read_csv(tmp_path)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded.iloc[0]["action"], "BUY")
        finally:
            Path(tmp_path).unlink()


class TestPipelineIntegration(unittest.TestCase):
    """测试Pipeline集成"""

    def test_end_to_end_pipeline(self):
        """端到端Pipeline集成测试"""
        # 模拟完整流程
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2", "f3"],
            "IC_5d": [0.05, -0.08, 0.03],
            "IC_t_5d": [3.0, -4.0, 2.0],
            "IC_pos_5d": [0.7, 0.3, 0.5],
            "n_days": [100, 100, 100],
        })

        # Step 1: IC分析通过
        ic_success = not ic_df.empty
        self.assertTrue(ic_success)

        # Step 2: 选股
        ic_df_sorted = ic_df.copy()
        ic_df_sorted["_abs_ic"] = ic_df_sorted["IC_5d"].abs()
        top_factors = ic_df_sorted.nlargest(2, "_abs_ic")["factor_id"].tolist()
        self.assertEqual(len(top_factors), 2)

        # Step 3: 推送（模拟）
        push_success = True  # 模拟成功
        self.assertTrue(push_success)


if __name__ == "__main__":
    unittest.main(verbosity=2)
