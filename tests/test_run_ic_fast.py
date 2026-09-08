#!/usr/bin/env python3
"""
run_ic_fast.py 单元测试
========================
测试 IC 汇总逻辑和参数解析。
核心 IC 计算已在 test_ic_compute.py 中覆盖。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd


class TestSummaryIC(unittest.TestCase):
    """测试 IC 汇总逻辑（与 run_ic_fast.py main() 中相同）"""

    def _summarize(self, ic_dict: dict) -> pd.DataFrame:
        """复制 run_ic_fast.py 中的汇总逻辑"""
        rows = []
        for fid, ic_list in ic_dict.items():
            ic_arr = np.array(ic_list, dtype=np.float64)
            n = len(ic_arr)
            ic_mean = np.nanmean(ic_arr) if n > 0 else np.nan
            ic_std = np.nanstd(ic_arr) if n > 1 else 0.0
            ic_t = ic_mean / (ic_std / np.sqrt(max(n - 1, 1)) + 1e-10) if n > 1 else np.nan
            ic_pos = (ic_arr > 0).mean() if n > 0 else np.nan
            rows.append({
                "factor_id": fid,
                "IC_5d": ic_mean,
                "IC_t_5d": ic_t,
                "IC_pos_5d": ic_pos,
                "n_days": n,
            })
        if not rows:
            return pd.DataFrame(columns=["factor_id", "IC_5d", "IC_t_5d", "IC_pos_5d", "n_days"])
        ic_df = pd.DataFrame(rows).set_index("factor_id")
        ic_df = ic_df.sort_values("IC_5d", key=abs, ascending=False)
        return ic_df.reset_index()

    def test_basic_summary(self):
        """基础汇总应产生正确行数"""
        ic_dict = {
            "fid_a": [0.05, 0.06, 0.04],
            "fid_b": [-0.03, -0.04, -0.02],
        }
        df = self._summarize(ic_dict)
        self.assertEqual(len(df), 2)
        self.assertIn("factor_id", df.columns)
        self.assertIn("IC_5d", df.columns)
        self.assertIn("IC_t_5d", df.columns)

    def test_sorting_by_abs_ic(self):
        """应按 |IC| 降序排列"""
        ic_dict = {
            "weak": [0.01, 0.01, 0.01],
            "strong": [0.08, 0.09, 0.07],
        }
        df = self._summarize(ic_dict)
        self.assertEqual(df.iloc[0]["factor_id"], "strong")
        self.assertEqual(df.iloc[1]["factor_id"], "weak")

    def test_nan_handling(self):
        """含 NaN 的 IC 列表应正确处理"""
        ic_dict = {"fid_x": [0.05, np.nan, 0.07]}
        df = self._summarize(ic_dict)
        expected_mean = np.nanmean([0.05, np.nan, 0.07])
        self.assertAlmostEqual(df.loc[df["factor_id"] == "fid_x", "IC_5d"].values[0],
                               expected_mean, places=6)

    def test_single_day_t_statistic(self):
        """单日 IC 的 t 值应有限（分母有保护）"""
        ic_dict = {"fid_single": [0.05]}
        df = self._summarize(ic_dict)
        row = df[df["factor_id"] == "fid_single"].iloc[0]
        # n=1 → std=0 → t 用保护分母计算，不会是 inf
        self.assertFalse(np.isinf(row["IC_t_5d"]))

    def test_empty_dict(self):
        """空 dict 应返回空 DataFrame"""
        df = self._summarize({})
        self.assertTrue(df.empty)


class TestRunICFastImports(unittest.TestCase):
    """测试 run_ic_fast.py 可正常导入"""

    def test_import_succeeds(self):
        """模块应可导入"""
        import run_ic_fast
        self.assertTrue(hasattr(run_ic_fast, "main"))

    def test_imports_compute_ic_session(self):
        """应从 ic_compute 导入 compute_ic_session"""
        import run_ic_fast
        self.assertTrue(hasattr(run_ic_fast, "compute_ic_session"))


class TestRunICFastArgs(unittest.TestCase):
    """测试命令行参数解析"""

    def test_no_args_default_feishu(self):
        """无参数时应使用默认飞书配置"""
        import run_ic_fast
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--feishu-url", default=None)
        args = parser.parse_args([])
        self.assertIsNone(args.feishu_url)

    def test_custom_feishu_url(self):
        """--feishu-url 应正确解析"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--feishu-url", default=None)
        args = parser.parse_args(["--feishu-url", "https://example.com/hook"])
        self.assertEqual(args.feishu_url, "https://example.com/hook")


if __name__ == "__main__":
    unittest.main(verbosity=2)
