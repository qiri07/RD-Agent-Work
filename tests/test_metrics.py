#!/usr/bin/env python3
"""
绩效分析模块测试
================
测试 engine/metrics.py 的所有功能。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
from datetime import timedelta

from engine.metrics import PerformanceAnalyzer, create_performance_analyzer, PerformanceMetrics


class TestPerformanceAnalyzerMetrics(unittest.TestCase):
    """测试绩效指标计算"""

    def setUp(self):
        self.analyzer = create_performance_analyzer(initial_capital=1_000_000)

    def test_positive_return(self):
        """正收益测试"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_100_000},
            {'date': pd.Timestamp('2024-01-03'), 'value': 1_200_000},
        ]
        metrics = self.analyzer.analyze(daily_value, [])
        self.assertGreater(metrics.total_return_pct, 0)
        self.assertGreater(metrics.final_nav, 1.0)

    def test_negative_return(self):
        """负收益测试"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 900_000},
            {'date': pd.Timestamp('2024-01-03'), 'value': 800_000},
        ]
        metrics = self.analyzer.analyze(daily_value, [])
        self.assertLess(metrics.total_return_pct, 0)
        self.assertLess(metrics.final_nav, 1.0)

    def test_sharpe_ratio_positive(self):
        """正夏普比率"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_010_000},
            {'date': pd.Timestamp('2024-01-03'), 'value': 1_020_200},
        ]
        metrics = self.analyzer.analyze(daily_value, [])
        self.assertGreater(metrics.sharpe_ratio, 0)

    def test_max_drawdown(self):
        """最大回撤计算"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_200_000},
            {'date': pd.Timestamp('2024-01-03'), 'value': 1_000_000},  # 回撤20%
        ]
        metrics = self.analyzer.analyze(daily_value, [])
        self.assertAlmostEqual(metrics.max_drawdown_pct, -16.67, places=2)

    def test_win_rate(self):
        """胜率计算"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_100_000},
            {'date': pd.Timestamp('2024-01-03'), 'value': 1_050_000},
        ]
        trades = [
            {'action': 'SELL', 'pnl_pct': 10},  # 盈利
            {'action': 'SELL', 'pnl_pct': -5},   # 亏损
        ]
        metrics = self.analyzer.analyze(daily_value, trades)
        self.assertEqual(metrics.win_rate_pct, 50.0)

    def test_profit_factor(self):
        """盈亏比计算"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_200_000},
        ]
        trades = [
            {'action': 'SELL', 'pnl_pct': 20},   # 盈利20%
            {'action': 'SELL', 'pnl_pct': -10},  # 亏损10%
        ]
        metrics = self.analyzer.analyze(daily_value, trades)
        self.assertEqual(metrics.profit_factor, 2.0)  # 20/10 = 2

    def test_zero_std_sharpe(self):
        """零波动夏普比率为0"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-03'), 'value': 1_000_000},
        ]
        metrics = self.analyzer.analyze(daily_value, [])
        self.assertEqual(metrics.sharpe_ratio, 0)


class TestPerformanceAnalyzerPeriod(unittest.TestCase):
    """测试期间分析"""

    def setUp(self):
        self.analyzer = create_performance_analyzer()

    def test_analyze_period_normal(self):
        """正常期间分析"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_100_000},
            {'date': pd.Timestamp('2024-01-03'), 'value': 1_200_000},
        ]
        result = self.analyzer.analyze_period(daily_value, '2024-01-01', '2024-01-03')
        self.assertIn('return', result)
        self.assertGreater(result['return'], 0)

    def test_analyze_period_insufficient_data(self):
        """数据不足返回0"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
        ]
        result = self.analyzer.analyze_period(daily_value, '2024-01-01', '2024-01-02')
        self.assertEqual(result['return'], 0)

    def test_analyze_period_out_of_range(self):
        """超出范围返回0"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_100_000},
        ]
        result = self.analyzer.analyze_period(daily_value, '2025-01-01', '2025-01-02')
        self.assertEqual(result['return'], 0)


class TestPerformanceAnalyzerStats(unittest.TestCase):
    """测试月度/年度统计"""

    def setUp(self):
        self.analyzer = create_performance_analyzer()

    def test_monthly_stats(self):
        """月度统计"""
        daily_value = []
        start = pd.Timestamp('2024-01-01')
        for i in range(60):  # 2个月
            daily_value.append({
                'date': start + timedelta(days=i),
                'value': 1_000_000 * (1 + i * 0.001)
            })

        monthly = self.analyzer.monthly_stats(daily_value)
        self.assertIsInstance(monthly, pd.DataFrame)
        self.assertGreater(len(monthly), 0)
        self.assertIn('ret', monthly.columns)

    def test_annual_stats(self):
        """年度统计"""
        daily_value = []
        start = pd.Timestamp('2024-01-01')
        for i in range(365):  # 1年
            daily_value.append({
                'date': start + timedelta(days=i),
                'value': 1_000_000 * (1 + i * 0.0005)
            })

        annual = self.analyzer.annual_stats(daily_value)
        self.assertIsInstance(annual, pd.DataFrame)
        self.assertGreater(len(annual), 0)
        self.assertIn('ret', annual.columns)
        self.assertIn('dd', annual.columns)


class TestPerformanceAnalyzerReport(unittest.TestCase):
    """测试报告生成"""

    def setUp(self):
        self.analyzer = create_performance_analyzer(initial_capital=1_000_000)

    def test_generate_report(self):
        """报告生成"""
        metrics = PerformanceMetrics(
            total_days=100,
            total_return_pct=15.5,
            annual_return_pct=20.3,
            sharpe_ratio=1.5,
            max_drawdown_pct=-8.5,
            win_rate_pct=55.0,
            total_trades=50,
            win_trades=28,
            profit_factor=1.8,
            final_value=1_155_000,
            final_nav=1.155
        )

        report = self.analyzer.generate_report(metrics, "Test Strategy")
        self.assertIn("Test Strategy", report)
        self.assertIn("15.50%", report)
        self.assertIn("1.500", report)
        self.assertIn("-8.50%", report)
        self.assertIn("55.0%", report)

    def test_generate_report_default_title(self):
        """默认标题"""
        metrics = PerformanceMetrics(
            total_days=10, total_return_pct=5.0, annual_return_pct=50.0,
            sharpe_ratio=1.0, max_drawdown_pct=-5.0, win_rate_pct=60.0,
            total_trades=10, win_trades=6, profit_factor=1.5,
            final_value=1_050_000, final_nav=1.05
        )
        report = self.analyzer.generate_report(metrics)
        self.assertIn("回测报告", report)


class TestPerformanceAnalyzerEdgeCases(unittest.TestCase):
    """测试边界情况"""

    def setUp(self):
        self.analyzer = create_performance_analyzer()

    def test_infinite_profit_factor(self):
        """全部盈利时盈亏比为inf"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_200_000},
        ]
        trades = [
            {'action': 'SELL', 'pnl_pct': 20},
            {'action': 'SELL', 'pnl_pct': 10},
        ]
        metrics = self.analyzer.analyze(daily_value, trades)
        self.assertEqual(metrics.profit_factor, 999.99)  # 限制为999.99

    def test_no_sells(self):
        """无卖出交易"""
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_100_000},
        ]
        trades = [
            {'action': 'BUY', 'pnl_pct': 0},
        ]
        metrics = self.analyzer.analyze(daily_value, trades)
        self.assertEqual(metrics.win_rate_pct, 0)
        self.assertEqual(metrics.profit_factor, 0)  # 无卖出交易，盈亏比应为0
        self.assertEqual(metrics.profit_factor, 0)

    def test_string_date_index(self):
        """字符串日期索引"""
        daily_value = [
            {'date': '2024-01-01', 'value': 1_000_000},
            {'date': '2024-01-02', 'value': 1_100_000},
        ]
        metrics = self.analyzer.analyze(daily_value, [])
        self.assertGreater(metrics.total_return_pct, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
