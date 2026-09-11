#!/usr/bin/env python3
"""
engine/recompute.py 单元测试
============================
测试 run_phase1_recompute、run_phase2_ic_analysis、generate_ic_report 等功能。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.recompute import (
    run_phase1_recompute, run_phase2_ic_analysis,
    ic_analysis_yearly, generate_ic_report, print_summary,
)


class TestGenerateICReport(unittest.TestCase):
    """测试 generate_ic_report"""

    def test_basic_report(self):
        """基本报告生成"""
        ic_df = pd.DataFrame({
            'factor_id': ['f1', 'f2'],
            'IC_5d': [0.05, -0.03],
            'IC_t_5d': [3.2, -2.1],
            'IC_pos_ratio_5d': [0.6, 0.4],
            'n_days': [200, 180],
        })
        report = generate_ic_report(ic_df)
        self.assertIsInstance(report, pd.DataFrame)
        self.assertEqual(len(report), 2)
        self.assertIn('abs_IC', report.columns)
        self.assertIn('ICIR', report.columns)

    def test_report_with_yearly_columns(self):
        """含年度IC列的报告"""
        ic_df = pd.DataFrame({
            'factor_id': ['f1'],
            'IC_5d': [0.05],
            'IC_t_5d': [3.0],
            'IC_pos_ratio_5d': [0.55],
            'n_days': [200],
            'IC_2023': [0.04],
            'IC_2024': [0.06],
            'IC_2025': [0.05],
            'IC_2026': [np.nan],
        })
        report = generate_ic_report(ic_df)
        self.assertIn('IC_mean', report.columns)
        self.assertIn('IC_std', report.columns)
        self.assertIn('IC_cv', report.columns)

    def test_report_empty(self):
        """空DataFrame"""
        ic_df = pd.DataFrame(columns=['factor_id', 'IC_5d'])
        report = generate_ic_report(ic_df)
        self.assertIsInstance(report, pd.DataFrame)
        self.assertEqual(len(report), 0)


class TestICAnalysisYearly(unittest.TestCase):
    """测试 ic_analysis_yearly"""

    def _make_factor_series(self, n_days=200, n_stocks=100):
        dates = pd.date_range('2023-01-01', periods=n_days, freq='B')
        stocks = [f'SH{i:06d}' for i in range(n_stocks)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        return pd.Series(np.random.rand(len(idx)), index=idx)

    def _make_returns_df(self, n_days=200, n_stocks=100):
        dates = pd.date_range('2023-01-01', periods=n_days, freq='B')
        stocks = [f'SH{i:06d}' for i in range(n_stocks)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        # ic_analysis_yearly 需要 "return" 列
        df = pd.DataFrame({'return': np.random.rand(len(idx))}, index=idx)
        return df

    def test_yearly_analysis_basic(self):
        """基本年度IC分析"""
        factor_series = self._make_factor_series()
        returns_df = self._make_returns_df()
        result = ic_analysis_yearly({'test_factor': factor_series}, returns_df)
        # 结果可能是 DataFrame 或 None（取决于数据是否满足阈值）
        if result is not None:
            self.assertIsInstance(result, pd.DataFrame)
            self.assertIn('factor_id', result.columns)
            self.assertIn('year', result.columns)
            self.assertIn('IC', result.columns)

    def test_yearly_analysis_empty(self):
        """空因子列表"""
        returns_df = self._make_returns_df()
        result = ic_analysis_yearly({}, returns_df)
        self.assertIsNone(result)

    def test_yearly_analysis_insufficient_data(self):
        """数据不足返回None"""
        short_idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(30)]
        )
        short_factor = pd.Series(np.random.rand(30), index=short_idx)
        returns_df = self._make_returns_df(n_days=5, n_stocks=30)
        result = ic_analysis_yearly({'short': short_factor}, returns_df)
        self.assertIsNone(result)


class TestRunPhase1Recompute(unittest.TestCase):
    """测试 run_phase1_recompute（mock sessions）"""

    def test_no_sessions(self):
        """无会话时返回空列表"""
        with mock.patch('batch_recompute_factors.get_sessions', return_value=[]):
            success, fail = run_phase1_recompute()
            self.assertEqual(success, [])
            self.assertEqual(fail, [])

    def test_session_recompute_success(self):
        """成功重算"""
        mock_session = mock.MagicMock()
        mock_session.name = 'test_session'
        with mock.patch('batch_recompute_factors.get_sessions', return_value=[mock_session]), \
             mock.patch('batch_recompute_factors.copy_data_to_session', return_value=True), \
             mock.patch('batch_recompute_factors.recompute_factor', return_value=(True, 'IC=0.05')):
            success, fail = run_phase1_recompute()
            self.assertEqual(len(success), 1)
            self.assertEqual(success[0][0], 'test_session')
            self.assertEqual(len(fail), 0)

    def test_session_recompute_failure(self):
        """失败的重算"""
        mock_session = mock.MagicMock()
        mock_session.name = 'bad_session'
        with mock.patch('batch_recompute_factors.get_sessions', return_value=[mock_session]), \
             mock.patch('batch_recompute_factors.copy_data_to_session', return_value=True), \
             mock.patch('batch_recompute_factors.recompute_factor', return_value=(False, 'Error: no data')):
            success, fail = run_phase1_recompute()
            self.assertEqual(len(success), 0)
            self.assertEqual(len(fail), 1)
            self.assertEqual(fail[0][0], 'bad_session')


class TestRunPhase2ICAnalysis(unittest.TestCase):
    """测试 run_phase2_ic_analysis（mock）"""

    def test_no_factors(self):
        """无因子结果"""
        with mock.patch('engine.recompute._load_factor_results', return_value={}), \
             mock.patch('engine.recompute.logger'):
            result = run_phase2_ic_analysis()
            self.assertIsNone(result)

    def test_phase2_success(self):
        """成功 Phase 2"""
        ic_df = pd.DataFrame({
            'factor_id': ['f1'],
            'IC_5d': [0.05],
            'IC_t_5d': [3.0],
            'IC_pos_ratio_5d': [0.6],
            'n_days': [200],
        })
        import engine.recompute as recompute_mod
        with mock.patch.object(recompute_mod, '_load_factor_results', return_value={'f1': pd.Series([1.0])}), \
             mock.patch.object(recompute_mod, '_load_returns'), \
             mock.patch('engine.ic_scan.ic_analysis', return_value=ic_df), \
             mock.patch.object(recompute_mod, 'ic_analysis_yearly', return_value=None):
            result = recompute_mod.run_phase2_ic_analysis()
            self.assertIsNotNone(result)
            ic_res, yearly_res, report = result
            self.assertIsInstance(ic_res, pd.DataFrame)
            self.assertIsNone(yearly_res)
            self.assertIsInstance(report, pd.DataFrame)


class TestPrintSummary(unittest.TestCase):
    """测试 print_summary（验证不抛异常）"""

    def test_print_summary_none(self):
        """None 输入"""
        print_summary(None)  # 不应抛出异常

    def test_print_summary_empty(self):
        """空DataFrame"""
        ic_df = pd.DataFrame(columns=['factor_id', 'IC_5d'])
        print_summary(ic_df)  # 不应抛出异常

    def test_print_summary_with_data(self):
        """有数据"""
        ic_df = pd.DataFrame({
            'factor_id': ['f1', 'f2'],
            'IC_5d': [0.05, -0.03],
            'IC_t_5d': [3.2, -2.1],
            'IC_pos_ratio_5d': [0.6, 0.4],
        })
        print_summary(ic_df)  # 不应抛出异常


class TestRunFullRecompute(unittest.TestCase):
    """测试 run_full_recompute（mock）"""

    def test_full_recompute_success(self):
        """完整流程成功"""
        ic_df = pd.DataFrame({
            'factor_id': ['f1'],
            'IC_5d': [0.05],
            'IC_t_5d': [3.0],
            'IC_pos_ratio_5d': [0.6],
            'n_days': [200],
        })
        import engine.recompute as recompute_mod
        with mock.patch.object(recompute_mod, 'run_phase1_recompute', return_value=([], [])), \
             mock.patch.object(recompute_mod, 'run_phase2_ic_analysis', return_value=(ic_df, None, ic_df)):
            result = recompute_mod.run_full_recompute()
            self.assertIsNotNone(result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
