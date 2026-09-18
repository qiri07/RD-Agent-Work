#!/usr/bin/env python3
from __future__ import annotations
"""
engine/recompute.py 单元测试
=============================
测试 run_phase1_recompute, run_phase2_ic_analysis, 
ic_analysis_yearly, generate_ic_report, print_summary 等功能。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.recompute import (
    run_phase2_ic_analysis,
    ic_analysis_yearly,
    generate_ic_report,
    print_summary,
)


class TestGenerateICReport(unittest.TestCase):
    """测试 generate_ic_report 函数"""

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
        })
        report = generate_ic_report(ic_df)
        self.assertIn('IC_mean', report.columns)
        self.assertIn('IC_std', report.columns)
        self.assertIn('IC_cv', report.columns)

    def test_report_empty(self):
        """空报告"""
        ic_df = pd.DataFrame()
        report = generate_ic_report(ic_df)
        self.assertIsInstance(report, pd.DataFrame)
        self.assertEqual(len(report), 0)


class TestIcAnalysisYearly(unittest.TestCase):
    """测试 ic_analysis_yearly 函数"""

    def test_yearly_analysis_empty(self):
        """空因子结果"""
        result = ic_analysis_yearly({}, pd.DataFrame())
        self.assertIsNone(result)

    def test_yearly_analysis_insufficient_data(self):
        """数据不足"""
        idx = pd.MultiIndex.from_tuples([
            (pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(50)
        ])
        factor_results = {'factor_1': pd.Series(np.random.randn(50), index=idx)}
        returns_df = pd.DataFrame({'return': np.random.randn(50)}, index=idx)
        
        result = ic_analysis_yearly(factor_results, returns_df)
        self.assertIsNone(result)


class TestPrintSummary(unittest.TestCase):
    """测试 print_summary 函数"""

    def test_print_summary_empty(self):
        """空DataFrame"""
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        print_summary(pd.DataFrame())
        sys.stdout = old_stdout
        output = buffer.getvalue()
        self.assertIn("无IC分析结果", output)

    def test_print_summary_none(self):
        """None输入"""
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        print_summary(None)
        sys.stdout = old_stdout
        output = buffer.getvalue()
        self.assertIn("无IC分析结果", output)

    def test_print_summary_with_data(self):
        """含数据的DataFrame"""
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        ic_df = pd.DataFrame({
            'factor_id': ['f1', 'f2'],
            'IC_5d': [0.05, -0.03],
            'IC_t_5d': [3.0, -2.0],
            'IC_pos_ratio_5d': [0.6, 0.4],
        })
        print_summary(ic_df)
        sys.stdout = old_stdout
        output = buffer.getvalue()
        self.assertIn("Top 10", output)
        self.assertIn("f1", output)


class TestRunPhase2IcAnalysis(unittest.TestCase):
    """测试 run_phase2_ic_analysis 函数"""

    @mock.patch('engine.recompute.orchestrator.load_factor_results')
    @mock.patch('engine.recompute.orchestrator.load_returns')
    def test_no_factors(self, mock_load_returns, mock_load_factors):
        """无因子结果"""
        mock_load_factors.return_value = {}
        result = run_phase2_ic_analysis()
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
