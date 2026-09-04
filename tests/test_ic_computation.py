#!/usr/bin/env python3
"""
IC 计算逻辑单元测试 — 使用 unittest
"""
import math
import unittest
import numpy as np
import pandas as pd
from scipy.stats import rankdata


def compute_ic_spearman(factors: np.ndarray, returns: np.ndarray) -> float:
    """参考 run_ic_fast.py 的 IC 计算方法"""
    mask = ~(np.isnan(factors) | np.isnan(returns))
    f = factors[mask]
    r = returns[mask]
    if len(f) < 2:
        return np.nan
    rf = rankdata(f)
    rr = rankdata(r)
    n = len(f)
    fc = rf - (n + 1) / 2
    rc = rr - (n + 1) / 2
    denom = np.sqrt(np.sum(fc * fc) * np.sum(rc * rc))
    if denom < 1e-15:
        return np.nan
    return float(np.sum(fc * rc) / denom)


def summarize_ic(results: dict) -> pd.DataFrame:
    """参考 run_ic_fast.py 的 summarize 函数"""
    rows = []
    for fid, ic_arr in results.items():
        arr = np.array(ic_arr, dtype=np.float64) if ic_arr else np.array([np.nan])
        n = len(arr)
        ic_mean = float(np.nanmean(arr)) if n > 0 else np.nan
        ic_std = float(np.nanstd(arr)) if n > 1 else 0.0
        ic_t = ic_mean / (ic_std / np.sqrt(max(n - 1, 1)) + 1e-10) if n > 1 else np.nan
        ic_pos = float((arr > 0).mean()) if n > 0 else np.nan
        rows.append({
            "factor_id": fid,
            "IC_5d": ic_mean,
            "IC_t_5d": ic_t,
            "IC_pos_5d": ic_pos,
            "n_days": n,
        })
    df = pd.DataFrame(rows).set_index("factor_id")
    df = df.sort_values("IC_5d", key=abs, ascending=False)
    return df


class TestICComputation(unittest.TestCase):
    def test_perfect_positive(self):
        f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        r = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
        ic = compute_ic_spearman(f, r)
        self.assertAlmostEqual(ic, 1.0, places=10)

    def test_perfect_negative(self):
        f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        r = np.array([10.0, 8.0, 6.0, 4.0, 2.0])
        ic = compute_ic_spearman(f, r)
        self.assertAlmostEqual(ic, -1.0, places=10)

    def test_random_weak_correlation(self):
        rng = np.random.default_rng(42)
        f = rng.standard_normal(200)
        r = rng.standard_normal(200)
        ic = compute_ic_spearman(f, r)
        self.assertLess(abs(ic), 0.2)

    def test_with_nan(self):
        f = np.array([1.0, np.nan, 3.0, 4.0, 5.0])
        r = np.array([2.0, 3.0, np.nan, 8.0, 10.0])
        ic = compute_ic_spearman(f, r)
        self.assertFalse(math.isnan(ic))

    def test_all_same_values(self):
        f = np.array([5.0, 5.0, 5.0, 5.0])
        r = np.array([1.0, 2.0, 3.0, 4.0])
        ic = compute_ic_spearman(f, r)
        self.assertTrue(math.isnan(ic))


class TestICSummarize(unittest.TestCase):
    def test_summary_basic(self):
        results = {
            "factor_a": [0.05, 0.06, 0.04],
            "factor_b": [-0.03, -0.04, -0.02],
        }
        df = summarize_ic(results)
        self.assertEqual(len(df), 2)
        self.assertGreater(df.loc["factor_a", "IC_5d"], 0)
        self.assertLess(df.loc["factor_b", "IC_5d"], 0)
        self.assertEqual(df.loc["factor_a", "n_days"], 3)

    def test_summary_sorting(self):
        results = {
            "weak": [0.01, 0.01, 0.01],
            "strong": [0.08, 0.09, 0.07],
        }
        df = summarize_ic(results)
        self.assertEqual(df.index[0], "strong")
        self.assertEqual(df.index[1], "weak")

    def test_summary_nan_mean(self):
        results = {"factor_x": [0.05, np.nan, 0.07]}
        df = summarize_ic(results)
        expected = np.nanmean([0.05, np.nan, 0.07])
        self.assertAlmostEqual(df.loc["factor_x", "IC_5d"], expected, places=10)


class TestRankData(unittest.TestCase):
    def test_rankdata_ties(self):
        arr = np.array([3.0, 1.0, 4.0, 1.0, 5.0])
        ranks = rankdata(arr)
        self.assertEqual(ranks[1], 1.5)  # tie at positions 1,3 → avg rank 1.5
        self.assertEqual(ranks[3], 1.5)
        self.assertEqual(ranks[0], 3.0)
        self.assertEqual(ranks[2], 4.0)
        self.assertEqual(ranks[4], 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
