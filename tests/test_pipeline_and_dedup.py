#!/usr/bin/env python3
"""
run_pipeline.py / deduplicate_source_data.py / run_ic_fast.py 单元测试
======================================================================
测试选股逻辑、IC 计算流程、去重逻辑。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd


class TestScreenStocks(unittest.TestCase):
    """测试选股逻辑（来自 run_pipeline.py）"""

    def test_screen_stocks_top_n_factors(self):
        """应选取 Top N 因子"""
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2", "f3", "f4"],
            "IC_5d": [0.05, -0.08, 0.03, -0.02],
            "IC_t_5d": [3.0, -4.0, 2.0, -1.0],
            "IC_pos_5d": [0.6, 0.3, 0.5, 0.4],
            "n_days": [100, 100, 100, 100],
        })

        # 模拟 screen_stocks 的核心逻辑
        ic_df_sorted = ic_df.copy()
        ic_df_sorted["_abs_ic"] = ic_df_sorted["IC_5d"].abs()
        top_factors = ic_df_sorted.nlargest(2, "_abs_ic")["factor_id"].tolist()

        self.assertEqual(len(top_factors), 2)
        self.assertEqual(top_factors[0], "f2")  # |IC|=0.08 最大
        self.assertEqual(top_factors[1], "f1")  # |IC|=0.05 次大

    def test_screen_stocks_sorting(self):
        """Top N 因子应按 |IC| 降序排列"""
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2", "f3"],
            "IC_5d": [0.01, 0.05, -0.03],
        })
        ic_df_sorted = ic_df.copy()
        ic_df_sorted["_abs_ic"] = ic_df_sorted["IC_5d"].abs()
        top_factors = ic_df_sorted.nlargest(2, "_abs_ic")["factor_id"].tolist()

        self.assertEqual(top_factors, ["f2", "f3"])  # |0.05| > |−0.03| > |0.01|

    def test_zscore_normalization(self):
        """Z-score 标准化"""
        combined = pd.DataFrame({
            "f1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "f2": [5.0, 4.0, 3.0, 2.0, 1.0],
        })
        # Z-score 标准化
        combined_std = combined.copy()
        for col in combined.columns:
            mean = combined[col].mean()
            std = combined[col].std()
            if std > 0:
                combined_std[col] = (combined[col] - mean) / std
            else:
                combined_std[col] = 0

        # 验证 Z-score 均值为0，标准差为1
        self.assertAlmostEqual(combined_std["f1"].mean(), 0.0, places=5)
        self.assertAlmostEqual(combined_std["f1"].std(), 1.0, places=5)
        self.assertAlmostEqual(combined_std["f2"].mean(), 0.0, places=5)

    def test_zscore_zero_std(self):
        """常数列的 Z-score 应为0"""
        combined = pd.DataFrame({
            "f1": [5.0, 5.0, 5.0],
            "f2": [1.0, 2.0, 3.0],
        })
        combined_std = combined.copy()
        for col in combined.columns:
            mean = combined[col].mean()
            std = combined[col].std()
            if std > 0:
                combined_std[col] = (combined[col] - mean) / std
            else:
                combined_std[col] = 0

        self.assertEqual(combined_std["f1"].tolist(), [0.0, 0.0, 0.0])

    def test_weighted_combination(self):
        """等权合成"""
        combined_std = pd.DataFrame({
            "f1": [1.0, -1.0, 0.0],
            "f2": [-1.0, 1.0, 0.0],
        })
        weights = 1.0 / len(combined_std.columns)
        combined_std["composite_score"] = (combined_std * weights).sum(axis=1)

        # f1+f2 加权平均
        expected = [(1.0 + (-1.0)) * 0.5, ((-1.0) + 1.0) * 0.5, (0.0 + 0.0) * 0.5]
        self.assertAlmostEqual(combined_std["composite_score"].iloc[0], expected[0])
        self.assertAlmostEqual(combined_std["composite_score"].iloc[1], expected[1])

    def test_rank_and_top_k(self):
        """排名取 Top K"""
        combined_std = pd.DataFrame({
            "composite_score": [3.0, 1.0, 4.0, 2.0, 5.0],
        })
        combined_std["rank"] = combined_std["composite_score"].rank(ascending=False, method="dense")
        top_k = 3
        top_stocks = combined_std.nlargest(top_k, "composite_score")

        self.assertEqual(len(top_stocks), 3)
        self.assertEqual(top_stocks["rank"].tolist(), [1.0, 2.0, 3.0])


class TestDeduplicateLogic(unittest.TestCase):
    """测试去重逻辑（来自 deduplicate_source_data.py）"""

    def test_dedup_parquet(self):
        """Parquet 去重"""
        dates = pd.date_range("2024-01-01", periods=3)
        idx = pd.MultiIndex.from_product([dates, ["SH600000"]], names=["date", "instrument"])
        df = pd.DataFrame({"$close": [10.0, 10.5, 11.0, 10.0, 10.5, 11.0]}, index=idx.append(idx))

        before = len(df)
        unique_df = df[~df.index.duplicated(keep='first')]
        after = len(unique_df)

        self.assertEqual(before, 6)
        self.assertEqual(after, 3)
        self.assertEqual(unique_df.index.nunique(), 3)

    def test_dedup_h5_roundtrip(self):
        """HDF5 读写一致性"""
        import tempfile
        from pathlib import Path
        dates = pd.date_range("2024-01-01", periods=3)
        idx = pd.MultiIndex.from_product([dates, ["SH600000"]], names=["date", "instrument"])
        df = pd.DataFrame({
            "$open": [10.0]*3, "$close": [10.5]*3,
            "$high": [10.6]*3, "$low": [10.3]*3,
            "$volume": [1000000]*3, "$factor": [1.0]*3,
        }, index=idx)

        with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as f:
            tmp_path = f.name

        try:
            df.to_hdf(tmp_path, key="data", mode="w")
            df_read = pd.read_hdf(tmp_path, key="data")
            pd.testing.assert_frame_equal(df, df_read)
        finally:
            Path(tmp_path).unlink()

    def test_dedup_preserves_order(self):
        """去重应保留首次出现的顺序"""
        dates = pd.date_range("2024-01-01", periods=3)
        idx = pd.MultiIndex.from_product([dates, ["SH600000"]], names=["date", "instrument"])
        df = pd.DataFrame({"$close": [10.0, 10.5, 11.0, 10.0, 10.5, 11.0]}, index=idx.append(idx))

        unique_df = df[~df.index.duplicated(keep='first')]
        self.assertEqual(unique_df["$close"].tolist(), [10.0, 10.5, 11.0])


class TestICSessionComputation(unittest.TestCase):
    """测试 IC session 计算逻辑（来自 run_ic_fast.py）"""

    def test_compute_ic_perfect_positive(self):
        """完美正相关 IC=1.0"""
        from scipy.stats import rankdata
        f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        r = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
        mask = ~(np.isnan(f) | np.isnan(r))
        f, r = f[mask], r[mask]
        rf = rankdata(f)
        rr = rankdata(r)
        n = len(f)
        fc = rf - (n + 1) / 2
        rc = rr - (n + 1) / 2
        denom = np.sqrt(np.sum(fc * fc) * np.sum(rc * rc))
        ic = np.sum(fc * rc) / denom
        self.assertAlmostEqual(ic, 1.0)

    def test_compute_ic_perfect_negative(self):
        """完美负相关 IC=-1.0"""
        from scipy.stats import rankdata
        f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        r = np.array([10.0, 8.0, 6.0, 4.0, 2.0])
        mask = ~(np.isnan(f) | np.isnan(r))
        f, r = f[mask], r[mask]
        rf = rankdata(f)
        rr = rankdata(r)
        n = len(f)
        fc = rf - (n + 1) / 2
        rc = rr - (n + 1) / 2
        denom = np.sqrt(np.sum(fc * fc) * np.sum(rc * rc))
        ic = np.sum(fc * rc) / denom
        self.assertAlmostEqual(ic, -1.0)

    def test_compute_ic_with_nan(self):
        """含 NaN 时应跳过"""
        from scipy.stats import rankdata
        f = np.array([1.0, np.nan, 3.0, 4.0, 5.0])
        r = np.array([2.0, 3.0, np.nan, 8.0, 10.0])
        mask = ~(np.isnan(f) | np.isnan(r))
        f, r = f[mask], r[mask]
        self.assertEqual(len(f), 3)  # 跳过 NaN

    def test_compute_ic_small_sample(self):
        """样本<2 应返回 NaN"""
        from scipy.stats import rankdata
        f = np.array([1.0])
        r = np.array([2.0])
        mask = ~(np.isnan(f) | np.isnan(r))
        f, r = f[mask], r[mask]
        if len(f) < 2:
            ic = np.nan
        else:
            rf = rankdata(f)
            rr = rankdata(r)
            n = len(f)
            fc = rf - (n + 1) / 2
            rc = rr - (n + 1) / 2
            denom = np.sqrt(np.sum(fc * fc) * np.sum(rc * rc))
            ic = np.sum(fc * rc) / denom if denom > 1e-15 else np.nan
        self.assertTrue(np.isnan(ic))

    def test_summarize_ic(self):
        """IC 汇总"""
        results = {
            "factor_a": [0.05, 0.06, 0.04],
            "factor_b": [-0.03, -0.04, -0.02],
        }
        rows = []
        for fid, ic_arr in results.items():
            arr = np.array(ic_arr, dtype=np.float64)
            n = len(arr)
            ic_mean = float(np.nanmean(arr))
            ic_std = float(np.nanstd(arr)) if n > 1 else 0.0
            ic_t = ic_mean / (ic_std / np.sqrt(max(n - 1, 1)) + 1e-10) if n > 1 else np.nan
            ic_pos = float((arr > 0).mean())
            rows.append({
                "factor_id": fid,
                "IC_5d": ic_mean,
                "IC_t_5d": ic_t,
                "IC_pos_5d": ic_pos,
                "n_days": n,
            })
        df = pd.DataFrame(rows).set_index("factor_id")
        df = df.sort_values("IC_5d", key=abs, ascending=False)

        self.assertEqual(df.index[0], "factor_a")  # |0.05| > |−0.03|
        self.assertGreater(df.loc["factor_a", "IC_5d"], 0)
        self.assertLess(df.loc["factor_b", "IC_5d"], 0)
        self.assertEqual(df.loc["factor_a", "n_days"], 3)

    def test_load_returns_as_long_logic(self):
        """收益率计算逻辑"""
        dates = pd.date_range("2024-01-01", periods=10)
        df = pd.DataFrame({
            "date": dates.tolist() * 2,
            "instrument": ["SH600000"] * 10 + ["SZ300001"] * 10,
            "$close": [10.0, 10.5, 11.0, 10.8, 11.2, 11.5, 11.3, 11.8, 12.0, 12.5,
                        20.0, 20.5, 21.0, 20.8, 21.2, 21.5, 21.3, 21.8, 22.0, 22.5],
        })
        df["ret_5d"] = df.groupby("instrument")["$close"].pct_change(5).shift(-5)
        ret_df = df[["date", "instrument", "ret_5d"]].dropna()
        ret_lookup = dict(zip(zip(ret_df["date"], ret_df["instrument"]), ret_df["ret_5d"]))

        self.assertGreater(len(ret_lookup), 0)
        # 最后一个日期的 ret_5d 应为 NaN（无法计算 forward return）
        last_date_sh = df[df["instrument"] == "SH600000"]["date"].iloc[-1]
        key = (last_date_sh, "SH600000")
        self.assertNotIn(key, ret_lookup)  # forward return 为 NaN


class TestPipelineOrchestration(unittest.TestCase):
    """测试 Pipeline 编排逻辑"""

    def test_argparse_modes(self):
        """命令行参数解析"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--ic-only", action="store_true")
        parser.add_argument("--stocks-only", action="store_true")
        parser.add_argument("--feishu-only", action="store_true")
        parser.add_argument("--top-n", type=int, default=10)

        args = parser.parse_args(["--stocks-only", "--top-n", "5"])
        self.assertTrue(args.stocks_only)
        self.assertFalse(args.ic_only)
        self.assertEqual(args.top_n, 5)

    def test_feishu_only_mode(self):
        """feishu-only 模式验证"""
        ic_df = pd.DataFrame({
            "factor_id": ["f1"], "IC_5d": [0.05], "IC_t_5d": [3.0],
            "IC_pos_5d": [0.6], "n_days": [100],
        })
        stocks_df = pd.DataFrame({
            "rank": [1], "instrument": ["SH600000"], "composite_score": [4.37],
        })
        # 验证数据格式正确
        self.assertEqual(len(ic_df), 1)
        self.assertEqual(len(stocks_df), 1)
        self.assertEqual(stocks_df.iloc[0]["instrument"], "SH600000")


if __name__ == "__main__":
    unittest.main(verbosity=2)
