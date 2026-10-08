#!/usr/bin/env python3
from __future__ import annotations
"""engine/strategy/*.py 测试（8 个子策略）"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.strategy.ma_cross import MaCrossStrategy
from engine.strategy.rsi import RsiStrategy
from engine.strategy.macd import MacdStrategy
from engine.strategy.bollinger import BollingerStrategy
from engine.strategy.cci import CciStrategy
from engine.strategy.kdj import KdjStrategy
from engine.strategy.adx import AdxDirectStrategy
from engine.strategy.volume_divergence import VolumeDivergenceStrategy


def _make_df(n=300):
    np.random.seed(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "close": 10 + np.cumsum(np.random.randn(n) * 0.015),
        "high":  10 + np.cumsum(np.abs(np.random.randn(n)) * 0.015) + 0.05,
        "low":   10 + np.cumsum(np.random.randn(n)) * 0.015 - 0.05,
        "volume": np.random.randint(1000, 10000, n),
    }, index=idx)


class TestMaCross(unittest.TestCase):
    def test_returns_series(self):
        sig = MaCrossStrategy.execute(_make_df())
        self.assertIsInstance(sig, pd.Series)
        self.assertTrue(set(sig.dropna().unique()).issubset({-1, 0, 1}))

    def test_has_signals(self):
        sig = MaCrossStrategy.execute(_make_df())
        self.assertGreater((sig != 0).sum(), 0)


class TestRsi(unittest.TestCase):
    def test_returns_series(self):
        sig = RsiStrategy.execute(_make_df())
        self.assertIsInstance(sig, pd.Series)
        self.assertTrue(set(sig.dropna().unique()).issubset({-1, 0, 1}))

    def test_has_signals(self):
        sig = RsiStrategy.execute(_make_df())
        self.assertGreater((sig != 0).sum(), 0)


class TestMacd(unittest.TestCase):
    def test_returns_series(self):
        sig = MacdStrategy.execute(_make_df())
        self.assertIsInstance(sig, pd.Series)
        self.assertTrue(set(sig.dropna().unique()).issubset({-1, 0, 1}))

    def test_has_signals(self):
        sig = MacdStrategy.execute(_make_df())
        self.assertGreater((sig != 0).sum(), 0)


class TestBollinger(unittest.TestCase):
    def test_returns_series(self):
        sig = BollingerStrategy.execute(_make_df())
        self.assertIsInstance(sig, pd.Series)
        self.assertTrue(set(sig.dropna().unique()).issubset({-1, 0, 1}))


class TestCci(unittest.TestCase):
    def test_returns_series(self):
        sig = CciStrategy.execute(_make_df())
        self.assertIsInstance(sig, pd.Series)
        self.assertTrue(set(sig.dropna().unique()).issubset({-1, 0, 1}))


class TestKdj(unittest.TestCase):
    def test_returns_series(self):
        sig = KdjStrategy.execute(_make_df())
        self.assertIsInstance(sig, pd.Series)
        self.assertTrue(set(sig.dropna().unique()).issubset({-1, 0, 1}))


class TestAdx(unittest.TestCase):
    def test_returns_series(self):
        sig = AdxDirectStrategy.execute(_make_df())
        self.assertIsInstance(sig, pd.Series)
        self.assertTrue(set(sig.dropna().unique()).issubset({-1, 0, 1}))


class TestVolumeDivergence(unittest.TestCase):
    def test_returns_series(self):
        sig = VolumeDivergenceStrategy.execute(_make_df())
        self.assertIsInstance(sig, pd.Series)
        self.assertTrue(set(sig.dropna().unique()).issubset({-1, 0, 1}))


if __name__ == "__main__":
    unittest.main()
