#!/usr/bin/env python3
"""
engine/ic_scan.py 单元测试
===========================
测试 compute_ic, ic_analysis, load_returns_from_sessions,
validate_data_consistency 等功能。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.ic_scan import (
    compute_ic,
    ic_analysis,
    load_returns_from_sessions,
    validate_data_consistency,
    IC_FORWARD_DAYS,
    IC_WINSORIZE,
    IC_MIN_STOCKS_PER_DAY,
)


class TestComputeIC(unittest.TestCase):
    """测试 compute_ic 函数"""

    def test_insufficient_data_returns_nan(self):
        """数据不足应返回NaN"""
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(100)]
        )
        factor = pd.Series(np.random.randn(100), index=idx)
        returns = pd.Series(np.random.randn(100), index=idx)
        result = compute_ic(factor, returns)
        self.assertTrue(pd.isna(result))

    def test_perfect_positive_correlation(self):
        """完全正相关应返回正IC"""
        n = 2000
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)]
        )
        factor = pd.Series(np.arange(n), index=idx, dtype=float)
        returns = pd.Series(np.arange(n).astype(float), index=idx)
        result = compute_ic(factor, returns)
        self.assertGreater(result, 0.9)

    def test_perfect_negative_correlation(self):
        """完全负相关应返回负IC"""
        n = 2000
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)]
        )
        factor = pd.Series(np.arange(n), index=idx, dtype=float)
        returns = pd.Series(np.arange(n, 0, -1).astype(float), index=idx)
        result = compute_ic(factor, returns)
        self.assertLess(result, -0.9)

    def test_multi_date_computes_daily_ic(self):
        """多日期数据应计算每日IC"""
        n_per_day = 200
        n_days = 20
        idx = pd.MultiIndex.from_tuples([
            (pd.Timestamp(f'2024-01-{d:02d}'), f'SH{i:06d}')
            for d in range(1, n_days + 1)
            for i in range(n_per_day)
        ])
        factor = pd.Series(np.random.randn(len(idx)), index=idx)
        returns = pd.Series(np.random.randn(len(idx)), index=idx)
        result = compute_ic(factor, returns)
        self.assertIsInstance(result, float)

    def test_all_nan_returns_nan(self):
        """全NaN数据应返回NaN"""
        n = 2000
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)]
        )
        factor = pd.Series([np.nan] * n, index=idx)
        returns = pd.Series(np.random.randn(n), index=idx)
        result = compute_ic(factor, returns)
        self.assertTrue(pd.isna(result))


class TestIcAnalysis(unittest.TestCase):
    """测试 ic_analysis 函数"""

    def test_basic_ic_analysis(self):
        """基本IC分析应返回DataFrame"""
        n = 3000
        idx = pd.MultiIndex.from_tuples([
            (pd.Timestamp(f'2024-01-{d:02d}'), f'SH{i:06d}')
            for d in range(1, 21)
            for i in range(150)
        ])
        factor_results = {
            'factor_1': pd.Series(np.random.randn(len(idx)), index=idx),
            'factor_2': pd.Series(np.random.randn(len(idx)), index=idx),
        }
        
        # 创建正确的returns_df格式
        dates = idx.get_level_values(0).unique()
        instruments = idx.get_level_values(1).unique()
        data = []
        for dt in dates:
            for inst in instruments:
                data.append({
                    'date': dt,
                    'instrument': inst,
                    '$close': np.random.randn() * 100 + 100,
                })
        returns_df = pd.DataFrame(data)
        
        result = ic_analysis(factor_results, returns_df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 2)

    def test_ic_analysis_empty(self):
        """空因子结果应返回空DataFrame"""
        result = ic_analysis({}, pd.DataFrame())
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    def test_ic_analysis_missing_factor(self):
        """缺少因子的情况应处理"""
        factor_results = {'factor_1': pd.Series([np.nan] * 100)}
        returns_df = pd.DataFrame({'$close': np.random.randn(100)})
        result = ic_analysis(factor_results, returns_df)
        self.assertIsInstance(result, pd.DataFrame)


class TestLoadReturnsFromSessions(unittest.TestCase):
    """测试 load_returns_from_sessions 函数"""

    def test_no_sessions_returns_empty(self):
        """无session应返回空DataFrame"""
        result = load_returns_from_sessions([])
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    @mock.patch('engine.ic_scan.logger')
    def test_session_without_parquet(self, mock_logger):
        """无parquet文件的session应被跳过"""
        session = mock.MagicMock()
        session.name = "test_session"
        session.__truediv__ = lambda self, x: Path("/nonexistent/path")
        session.exists = lambda: False
        
        result = load_returns_from_sessions([session])
        self.assertIsInstance(result, pd.DataFrame)


class TestValidateDataConsistency(unittest.TestCase):
    """测试 validate_data_consistency 函数"""

    def test_consistent_data_returns_true(self):
        """一致的数据应返回True"""
        n = 1000
        idx = pd.MultiIndex.from_tuples([
            (pd.Timestamp(f'2024-01-{d:02d}'), f'SH{i:06d}')
            for d in range(1, 11)
            for i in range(100)
        ])
        factor_results = {
            'factor_1': pd.Series(np.random.randn(len(idx)), index=idx),
        }
        returns_df = pd.DataFrame({'return': np.random.randn(len(idx))}, index=idx)
        
        result = validate_data_consistency(factor_results, returns_df)
        self.assertTrue(result)

    def test_inconsistent_data_returns_false(self):
        """不一致的数据应返回False"""
        idx1 = pd.MultiIndex.from_tuples([
            (pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(100)
        ])
        idx2 = pd.MultiIndex.from_tuples([
            (pd.Timestamp('2024-02-01'), f'SZ{i:06d}') for i in range(100)
        ])
        factor_results = {'factor_1': pd.Series(np.random.randn(100), index=idx1)}
        returns_df = pd.DataFrame({'return': np.random.randn(100)}, index=idx2)
        
        result = validate_data_consistency(factor_results, returns_df)
        self.assertFalse(result)

    def test_empty_factor_results(self):
        """空因子结果应返回False"""
        returns_df = pd.DataFrame({'return': np.random.randn(100)})
        result = validate_data_consistency({}, returns_df)
        self.assertFalse(result)


class TestConstants(unittest.TestCase):
    """测试模块常量"""

    def test_ic_forward_days(self):
        """IC_FORWARD_DAYS 应为 [1, 3, 5]"""
        self.assertEqual(IC_FORWARD_DAYS, [1, 3, 5])

    def test_ic_winsorize(self):
        """IC_WINSORIZE 应为 0.01"""
        self.assertEqual(IC_WINSORIZE, 0.01)

    def test_ic_min_stocks_per_day(self):
        """IC_MIN_STOCKS_PER_DAY 应为 50"""
        self.assertEqual(IC_MIN_STOCKS_PER_DAY, 50)


if __name__ == '__main__':
    unittest.main()
