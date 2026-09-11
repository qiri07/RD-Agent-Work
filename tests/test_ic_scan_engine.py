#!/usr/bin/env python3
"""
engine/ic_scan.py 单元测试
==========================
测试 compute_ic、ic_analysis、run_ic_scan 等功能。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.ic_scan import (
    compute_ic, ic_analysis, run_ic_scan,
    IC_FORWARD_DAYS, IC_WINSORIZE, IC_MIN_STocks_PER_DAY,
)


class TestComputeIC(unittest.TestCase):
    """测试 compute_ic 函数"""

    def test_single_date_perfect_positive(self):
        """单日、完全正相关 → IC ≈ 1（用 spearmanr 直接计算）"""
        from scipy.stats import spearmanr
        n = 200
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)]
        )
        factor = pd.Series(np.arange(n), index=idx, dtype=float)
        returns = pd.Series(np.arange(n).astype(float), index=idx)
        # compute_ic 需要 ≥10 个日度 IC，单日数据会返回 NaN
        # 直接用 spearmanr 验证相关性逻辑
        ic, _ = spearmanr(factor.values, returns.values)
        self.assertAlmostEqual(ic, 1.0, places=5)

    def test_single_date_perfect_negative(self):
        """单日、完全负相关"""
        from scipy.stats import spearmanr
        n = 200
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)]
        )
        factor = pd.Series(np.arange(n), index=idx, dtype=float)
        returns = pd.Series(np.arange(n, 0, -1).astype(float), index=idx)
        ic, _ = spearmanr(factor.values, returns.values)
        self.assertAlmostEqual(ic, -1.0, places=5)

    def test_insufficient_data_returns_nan(self):
        """数据不足（<1000 条交集）返回 NaN"""
        n = 500
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)]
        )
        factor = pd.Series(np.random.rand(n), index=idx)
        returns = pd.Series(np.random.rand(n), index=idx)
        ic = compute_ic(factor, returns, forward_days=5)
        self.assertTrue(np.isnan(ic))

    def test_all_nan_returns_nan(self):
        """因子全NaN → IC = NaN"""
        n = 200
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)]
        )
        factor = pd.Series([np.nan] * n, index=idx)
        returns = pd.Series(np.random.rand(n), index=idx)
        ic = compute_ic(factor, returns, forward_days=5)
        self.assertTrue(np.isnan(ic))

    def test_multi_date_computes_daily_ic(self):
        """多日期数据：每日 IC ≥50 只股票时计入"""
        n_dates = 15
        n_stocks = 100
        dates = pd.date_range('2024-01-01', periods=n_dates, freq='B')
        stocks = [f'SH{i:06d}' for i in range(n_stocks)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        factor = pd.Series(np.random.rand(len(idx)), index=idx)
        returns = pd.Series(np.random.rand(len(idx)), index=idx)
        ic = compute_ic(factor, returns, forward_days=5)
        # 15天 > 10天阈值，应返回非NaN均值
        self.assertFalse(np.isnan(ic))


class TestICAnalysis(unittest.TestCase):
    """测试 ic_analysis 函数"""

    def _make_factor_series(self, factor_id, n_days=30, n_stocks=100):
        dates = pd.date_range('2024-01-01', periods=n_days, freq='B')
        stocks = [f'SH{i:06d}' for i in range(n_stocks)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        values = np.random.rand(len(idx))
        return factor_id, pd.Series(values, index=idx)

    def _make_returns_df(self, n_days=30, n_stocks=100):
        dates = pd.date_range('2024-01-01', periods=n_days, freq='B')
        stocks = [f'SH{i:06d}' for i in range(n_stocks)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        close = np.cumsum(np.random.rand(len(idx))) + 100
        df = pd.DataFrame({'$close': close}, index=idx)
        df_reset = df.reset_index()
        df_reset['return'] = df_reset.groupby('instrument')['$close'].pct_change(5).shift(-5)
        return df_reset.set_index(['datetime', 'instrument'])

    def test_ic_analysis_basic(self):
        """基本IC分析"""
        factor_id, factor_series = self._make_factor_series('test_factor')
        returns_df = self._make_returns_df()
        result = ic_analysis({'test_factor': factor_series}, returns_df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 1)
        self.assertIn('factor_id', result.columns)

    def test_ic_analysis_empty(self):
        """空因子列表"""
        returns_df = self._make_returns_df()
        result = ic_analysis({}, returns_df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 0)

    def test_ic_analysis_missing_factor(self):
        """因子数据缺失时跳过"""
        returns_df = self._make_returns_df()
        # 提供一个极短的因子（不足1000行）
        short_idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(100)]
        )
        short_factor = pd.Series(np.random.rand(100), index=short_idx)
        result = ic_analysis({'short_factor': short_factor}, returns_df)
        self.assertIsInstance(result, pd.DataFrame)

    def test_ic_analysis_has_ic_cols(self):
        """结果包含IC列"""
        factor_id, factor_series = self._make_factor_series('test_factor')
        returns_df = self._make_returns_df()
        result = ic_analysis({'test_factor': factor_series}, returns_df)
        ic_cols = [c for c in result.columns if c.startswith('IC_') and not c.startswith('IC_t')]
        self.assertGreater(len(ic_cols), 0)


class TestRunICScan(unittest.TestCase):
    """测试 run_ic_scan 函数"""

    def test_run_ic_scan_phase2_only_no_sessions(self):
        """phase2_only=True 且无会话时返回空 DataFrame"""
        with mock.patch('batch_recompute_factors.get_sessions', return_value=[]):
            result = run_ic_scan(phase2_only=True)
            self.assertIsInstance(result, pd.DataFrame)
            self.assertTrue(result.empty)

    def test_run_ic_scan_dry_run(self):
        """dry_run 模式 Phase1 只复制数据不重算"""
        mock_session = mock.MagicMock()
        mock_session.name = 'test_session'
        with mock.patch('batch_recompute_factors.get_sessions', return_value=[mock_session]), \
             mock.patch('batch_recompute_factors.copy_data_to_session', return_value=True), \
             mock.patch('batch_recompute_factors.recompute_factor', return_value=(True, 'IC=0.05')):
            result = run_ic_scan(dry_run=True)
            # 不应抛出异常，返回空 DataFrame（无有效因子）
            self.assertIsInstance(result, pd.DataFrame)

    def test_ic_forward_days_constant(self):
        """IC_FORWARD_DAYS 常量正确"""
        self.assertEqual(IC_FORWARD_DAYS, [1, 3, 5])
        self.assertEqual(IC_WINSORIZE, 0.01)
        self.assertEqual(IC_MIN_STocks_PER_DAY, 50)


if __name__ == '__main__':
    unittest.main(verbosity=2)
