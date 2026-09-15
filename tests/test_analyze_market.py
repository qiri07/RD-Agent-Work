#!/usr/bin/env python3
"""
analyze_market.py 单元测试
===========================
测试 compute_all_factors_np, compute_forward_ret_np, stock_stats_np,
ic_numpy, backtest_np 等核心函数。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from analyze_market import (
    compute_all_factors_np,
    compute_forward_ret_np,
    stock_stats_np,
    ic_numpy,
    backtest_np,
    FACTOR_COLS,
    STRATEGIES,
)


class TestComputeAllFactorsNp(unittest.TestCase):
    """测试 compute_all_factors_np 函数"""

    def test_returns_dict_with_expected_keys(self):
        """返回字典包含预期的因子键"""
        close = np.random.randn(300).cumsum() + 100
        vol = np.random.rand(300) * 1e9 + 1e8
        factors = compute_all_factors_np(close, vol)
        
        expected_keys = [
            'momentum_5d', 'momentum_10d', 'momentum_20d', 'momentum_60d',
            'reversal_5d', 'volatility_10d', 'volatility_20d', 'volatility_60d',
            'volume_ratio', 'rsi_14', 'macd', 'macd_signal', 'macd_hist',
            'bollinger_pos'
        ]
        for key in expected_keys:
            self.assertIn(key, factors, f"Missing factor: {key}")

    def test_momentum_factors_shape(self):
        """动量因子形状与输入一致"""
        close = np.random.randn(300).cumsum() + 100
        vol = np.random.rand(300) * 1e9 + 1e8
        factors = compute_all_factors_np(close, vol)
        
        for p in [5, 10, 20, 60]:
            key = f'momentum_{p}d'
            self.assertEqual(len(factors[key]), len(close))
            # 前 p 个值应为 NaN
            self.assertTrue(np.all(np.isnan(factors[key][:p])))

    def test_reversal_5d_shape(self):
        """反转因子形状正确"""
        close = np.random.randn(300).cumsum() + 100
        vol = np.random.rand(300) * 1e9 + 1e8
        factors = compute_all_factors_np(close, vol)
        
        self.assertEqual(len(factors['reversal_5d']), len(close))
        self.assertTrue(np.all(np.isnan(factors['reversal_5d'][:5])))

    def test_rsi_range(self):
        """RSI 值在合理范围内 [0, 100]"""
        close = np.random.randn(300).cumsum() + 100
        vol = np.random.rand(300) * 1e9 + 1e8
        factors = compute_all_factors_np(close, vol)
        
        rsi = factors['rsi_14']
        valid_rsi = rsi[~np.isnan(rsi)]
        if len(valid_rsi) > 0:
            self.assertGreaterEqual(valid_rsi.min(), 0)
            self.assertLessEqual(valid_rsi.max(), 100)

    def test_bollinger_pos_reasonable(self):
        """布林带位置在合理范围内"""
        close = np.random.randn(300).cumsum() + 100
        vol = np.random.rand(300) * 1e9 + 1e8
        factors = compute_all_factors_np(close, vol)
        
        bb = factors['bollinger_pos']
        valid_bb = bb[~np.isnan(bb)]
        if len(valid_bb) > 0:
            # 大部分值应在 [-3, 3] 范围内
            self.assertGreaterEqual(valid_bb.min(), -10)
            self.assertLessEqual(valid_bb.max(), 10)

    def test_short_series(self):
        """短序列不应崩溃"""
        close = np.array([100.0, 101.0, 102.0])
        vol = np.array([1e8, 1e8, 1e8])
        factors = compute_all_factors_np(close, vol)
        self.assertIsInstance(factors, dict)


class TestComputeForwardRetNp(unittest.TestCase):
    """测试 compute_forward_ret_np 函数"""

    def test_returns_array_shape(self):
        """返回数组形状与输入一致"""
        close = np.random.randn(300).cumsum() + 100
        fr = compute_forward_ret_np(close)
        self.assertEqual(len(fr), len(close))

    def test_last_values_are_nan(self):
        """最后5个值应为NaN"""
        close = np.random.randn(300).cumsum() + 100
        fr = compute_forward_ret_np(close)
        self.assertTrue(np.all(np.isnan(fr[-5:])))

    def test_first_value_computed(self):
        """第一个值应被正确计算"""
        close = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        fr = compute_forward_ret_np(close)
        expected = 105.0 / 100.0 - 1  # 5日收益率
        self.assertAlmostEqual(fr[0], expected, places=5)


class TestStockStatsNp(unittest.TestCase):
    """测试 stock_stats_np 函数"""

    def test_returns_none_for_short_series(self):
        """短序列应返回None"""
        close = np.random.randn(100).cumsum() + 100
        dates = np.arange(100)
        result = stock_stats_np(close, dates)
        self.assertIsNone(result)

    def test_returns_dict_with_expected_keys(self):
        """返回字典包含预期键"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        dates = np.array(['2020-01-15'] * 300, dtype='datetime64')
        result = stock_stats_np(close, dates)
        
        expected_keys = [
            'n_days', 'price_min', 'price_max',
            'ann_return_pct', 'ann_volatility_pct', 'sharpe', 'max_drawdown_pct', 'yearly'
        ]
        for key in expected_keys:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_annualized_return_range(self):
        """年化收益率应在合理范围内"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        dates = np.array(['2020-01-15'] * 300, dtype='datetime64')
        result = stock_stats_np(close, dates)
        
        self.assertGreater(result['ann_return_pct'], -100)
        self.assertLess(result['ann_return_pct'], 1000)

    def test_sharpe_reasonable(self):
        """夏普比率应在合理范围内"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        dates = np.array(['2020-01-15'] * 300, dtype='datetime64')
        result = stock_stats_np(close, dates)
        
        self.assertGreater(result['sharpe'], -10)
        self.assertLess(result['sharpe'], 10)

    def test_with_integer_dates(self):
        """整数日期不应崩溃"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        dates = np.arange(300)
        result = stock_stats_np(close, dates)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['n_days'], 300)

    def test_with_datetime_dates(self):
        """datetime日期应正确处理"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        dates = pd.date_range('2020-01-01', periods=300, freq='D').values
        result = stock_stats_np(close, dates)
        
        self.assertIsNotNone(result)


class TestIcNumpy(unittest.TestCase):
    """测试 ic_numpy 函数"""

    def test_perfect_positive_correlation(self):
        """完全正相关应返回IC接近1"""
        np.random.seed(42)
        f_vals = np.random.randn(200)
        r_vals = f_vals + np.random.randn(200) * 0.1
        result = ic_numpy(f_vals, r_vals)
        
        self.assertIsNotNone(result)
        self.assertGreater(result['IC'], 0.9)

    def test_perfect_negative_correlation(self):
        """完全负相关应返回IC接近-1"""
        np.random.seed(42)
        f_vals = np.random.randn(200)
        r_vals = -f_vals + np.random.randn(200) * 0.1
        result = ic_numpy(f_vals, r_vals)
        
        self.assertIsNotNone(result)
        self.assertLess(result['IC'], -0.9)

    def test_no_correlation(self):
        """无相关应返回IC接近0"""
        np.random.seed(42)
        f_vals = np.random.randn(200)
        r_vals = np.random.randn(200)
        result = ic_numpy(f_vals, r_vals)
        
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['IC'], 0, delta=0.3)

    def test_insufficient_data_returns_none(self):
        """数据不足应返回None"""
        f_vals = np.random.randn(50)
        r_vals = np.random.randn(50)
        result = ic_numpy(f_vals, r_vals)
        self.assertIsNone(result)

    def test_with_nans(self):
        """含NaN数据应正确处理"""
        np.random.seed(42)
        f_vals = np.random.randn(200)
        r_vals = np.random.randn(200)
        f_vals[:10] = np.nan
        r_vals[:10] = np.nan
        result = ic_numpy(f_vals, r_vals)
        self.assertIsNotNone(result)

    def test_result_structure(self):
        """返回结果应包含预期字段"""
        np.random.seed(42)
        f_vals = np.random.randn(200)
        r_vals = np.random.randn(200)
        result = ic_numpy(f_vals, r_vals)
        
        expected_keys = ['IC', 'p_value', 'n', 'significant']
        for key in expected_keys:
            self.assertIn(key, result)


class TestBacktestNp(unittest.TestCase):
    """测试 backtest_np 函数"""

    def test_returns_dict_with_expected_keys(self):
        """返回字典包含预期键"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        factor = np.random.randn(300)
        result = backtest_np(close, factor, 'momentum_5d')
        
        expected_keys = ['strategy', 'final_value', 'return_pct', 'sharpe', 'max_drawdown_pct', 'n_trades']
        for key in expected_keys:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_momentum_5d_strategy(self):
        """momentum_5d 策略应能正常执行"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        factor = np.random.randn(300)
        result = backtest_np(close, factor, 'momentum_5d')
        self.assertIsInstance(result['return_pct'], float)

    def test_momentum_20d_strategy(self):
        """momentum_20d 策略应能正常执行"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        factor = np.random.randn(300)
        result = backtest_np(close, factor, 'momentum_20d')
        self.assertIsInstance(result['return_pct'], float)

    def test_reversal_5d_strategy(self):
        """reversal_5d 策略应能正常执行"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        factor = np.random.randn(300)
        result = backtest_np(close, factor, 'reversal_5d')
        self.assertIsInstance(result['return_pct'], float)

    def test_rsi_strategy(self):
        """RSI 策略应能正常执行"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        factor = np.random.randn(300)
        result = backtest_np(close, factor, 'rsi')
        self.assertIsInstance(result['return_pct'], float)

    def test_macd_strategy(self):
        """MACD 策略应能正常执行"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        factor = np.random.randn(300)
        result = backtest_np(close, factor, 'macd')
        self.assertIsInstance(result['return_pct'], float)

    def test_with_nan_factors(self):
        """含NaN的因子应被跳过"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        factor = np.random.randn(300)
        factor[:50] = np.nan  # 前50个值无效
        result = backtest_np(close, factor, 'momentum_5d')
        self.assertIsNotNone(result)

    def test_final_value_positive(self):
        """最终价值应为正数"""
        np.random.seed(42)
        close = np.random.randn(300).cumsum() + 100
        factor = np.random.randn(300)
        result = backtest_np(close, factor, 'momentum_5d')
        self.assertGreater(result['final_value'], 0)


class TestConstants(unittest.TestCase):
    """测试模块常量"""

    def test_factor_cols(self):
        """FACTOR_COLS 应包含8个因子"""
        self.assertEqual(len(FACTOR_COLS), 8)

    def test_strategies(self):
        """STRATEGIES 应包含5个策略"""
        self.assertEqual(len(STRATEGIES), 5)


if __name__ == '__main__':
    unittest.main()
