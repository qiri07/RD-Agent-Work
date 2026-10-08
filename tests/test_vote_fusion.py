#!/usr/bin/env python3
from __future__ import annotations
"""engine/vote_fusion.py 测试"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.vote_fusion import fuse_signals, apply_trend_filter, run_signal_pipeline


def _make_df(n=200):
    np.random.seed(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "close": 10 + np.cumsum(np.random.randn(n) * 0.015),
        "high":  10 + np.cumsum(np.abs(np.random.randn(n)) * 0.015) + 0.05,
        "low":   10 + np.cumsum(np.random.randn(n)) * 0.015 - 0.05,
        "volume": np.random.randint(1000, 10000, n),
    }, index=idx)


class TestFuseSignals(unittest.TestCase):
    """测试多策略投票融合"""

    def test_strict_majority(self):
        n = 10
        signals = [pd.Series([1] * n) for _ in range(5)]
        signals += [pd.Series([-1] * n) for _ in range(3)]
        result = fuse_signals(signals, threshold=2)
        self.assertTrue((result == 1).all())

    def test_below_threshold(self):
        n = 10
        s1 = pd.Series([1] * n)
        rest = [pd.Series([0] * n) for _ in range(7)]
        result = fuse_signals([s1] + rest, threshold=2)
        self.assertTrue((result == 0).all())

    def test_all_sell(self):
        n = 10
        signals = [pd.Series([-1] * n) for _ in range(8)]
        result = fuse_signals(signals, threshold=2)
        self.assertTrue((result == -1).all())

    def test_all_hold(self):
        n = 10
        signals = [pd.Series([0] * n) for _ in range(8)]
        result = fuse_signals(signals, threshold=2)
        self.assertTrue((result == 0).all())

    def test_mixed(self):
        n = 10
        signals = [pd.Series([1] * n) for _ in range(4)]
        signals += [pd.Series([-1] * n) for _ in range(4)]
        result = fuse_signals(signals, threshold=2)
        # buy=4 >= 2 and sell=4 >= 2 → conflict, but buy wins (first np.where)
        # Actually both conditions true → np.where picks first branch (buy=1)
        self.assertEqual(set(result.unique()), {1})

    def test_different_threshold(self):
        n = 10
        signals = [pd.Series([1] * n) for _ in range(4)]
        signals += [pd.Series([-1] * n) for _ in range(4)]
        result = fuse_signals(signals, threshold=5)
        self.assertTrue((result == 0).all())

    def test_empty_signals(self):
        result = fuse_signals([], threshold=2)
        self.assertEqual(len(result), 0)


class TestApplyTrendFilter(unittest.TestCase):
    """测试趋势过滤"""

    def test_blocks_sell_in_uptrend(self):
        df = _make_df().copy()
        # 构造后半段价格远高于 MA60（强上升趋势）
        baseline = df["close"].iloc[149]
        df.loc[df.index[150:], "close"] = baseline * 2.0
        # 信号：最后两行买入+卖出
        sig = pd.Series([0] * (len(df) - 2) + [1, -1], index=df.index)
        filtered = apply_trend_filter(df, sig, ma_window=60)
        # 强上升趋势中最后一行的卖出信号应被过滤为0
        self.assertEqual(filtered.iloc[-1], 0)

    def test_blocks_buy_in_downtrend(self):
        df = _make_df()
        df.loc[df.index[-3:], "close"] = df["close"].iloc[-4] * 0.8
        sig = pd.Series([1, -1, 1, -1], index=df.index[-4:])
        filtered = apply_trend_filter(df, sig, ma_window=60)
        # 下降趋势中买入信号应被过滤
        self.assertEqual(filtered.iloc[-2], 0)


class TestRunSignalPipeline(unittest.TestCase):
    """测试完整信号生成流水线"""

    def test_runs_all_8_strategies(self):
        df = _make_df()
        result = run_signal_pipeline(df, threshold=2, trend_filter=False)
        self.assertEqual(len(result["strategy_signals"]), 8)
        self.assertIn("signal", result)
        self.assertIn("buy_count", result)
        self.assertIn("sell_count", result)
        self.assertGreater(result["buy_count"] + result["sell_count"], 0)

    def test_returns_correct_keys(self):
        df = _make_df()
        result = run_signal_pipeline(df)
        self.assertIn("signal", result)
        self.assertIn("strategy_signals", result)
        self.assertIn("buy_count", result)
        self.assertIn("sell_count", result)
        self.assertIn("hold_count", result)

    def test_signal_values_are_minus_one_zero_or_one(self):
        df = _make_df()
        result = run_signal_pipeline(df)
        sig = result["signal"]
        self.assertTrue(set(sig.dropna().unique()).issubset({-1, 0, 1}))

    def test_trend_filter_reduces_signals(self):
        df = _make_df()
        with_trend  = run_signal_pipeline(df, trend_filter=True)
        without_trend = run_signal_pipeline(df, trend_filter=False)
        # 趋势过滤不应增加信号数量
        self.assertLessEqual(with_trend["buy_count"],  without_trend["buy_count"])
        self.assertLessEqual(with_trend["sell_count"], without_trend["sell_count"])


if __name__ == "__main__":
    unittest.main()
