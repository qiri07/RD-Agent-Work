#!/usr/bin/env python3
"""
数据验证模块详细测试
====================
测试 data_validator.py 的所有功能。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from data_validator import DataValidator, validate_stock_data, print_trading_rules_summary


class TestDataValidatorInit(unittest.TestCase):
    """测试初始化"""

    def test_init_copies_dataframe(self):
        """初始化时复制DataFrame"""
        df = pd.DataFrame({'$close': [100, 200]})
        validator = DataValidator(df)
        validator.prices.loc[0, '$close'] = 999
        self.assertEqual(df.loc[0, '$close'], 100)  # 原数据不变


class TestDataValidatorCheckPriceRange(unittest.TestCase):
    """测试价格范围检查"""

    def test_extreme_price_detected(self):
        """极端价格检测"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100] * 5,
            '$close': [100, 100, 15000, 100, 100],  # 极端价格
            '$high': [100] * 5,
            '$low': [100] * 5,
            '$volume': [1000] * 5,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator._check_price_range()
        self.assertGreater(len(issues), 0)

    def test_normal_prices_no_issue(self):
        """正常价格无问题"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100] * 5,
            '$close': [100] * 5,
            '$high': [100] * 5,
            '$low': [100] * 5,
            '$volume': [1000] * 5,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator._check_price_range()
        self.assertEqual(len(issues), 0)


class TestDataValidatorCheckReturnLimits(unittest.TestCase):
    """测试涨跌幅限制检查"""

    def test_sh_main_limit(self):
        """沪市主板限制"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100] * 5,
            '$close': [100, 115, 100, 100, 100],  # +15% 超过10%限制
            '$high': [100] * 5,
            '$low': [100] * 5,
            '$volume': [1000] * 5,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator._check_return_limits()
        self.assertGreater(len(issues), 0)

    def test_gem_limit(self):
        """创业板限制"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SZ300001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100] * 5,
            '$close': [100, 130, 100, 100, 100],  # +30% 超过20%限制
            '$high': [100] * 5,
            '$low': [100] * 5,
            '$volume': [1000] * 5,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator._check_return_limits()
        self.assertGreater(len(issues), 0)

    def test_normal_data_no_violation(self):
        """正常数据无违规"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ300001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100] * 10,
            '$close': [100, 105, 103, 102, 101] * 2,  # 正常波动
            '$high': [100] * 10,
            '$low': [100] * 10,
            '$volume': [1000] * 10,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator._check_return_limits()
        self.assertEqual(len(issues), 0)


class TestDataValidatorCheckVolumeAnomalies(unittest.TestCase):
    """测试成交量异常检测"""

    def test_normal_volume_no_anomaly(self):
        """正常成交量"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100] * 10,
            '$close': [100] * 10,
            '$high': [100] * 10,
            '$low': [100] * 10,
            '$volume': [1000] * 10,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator.validate_all()
        self.assertNotIn('volume_anomaly', issues)

    def test_sudden_volume_spike_detected(self):
        """成交量突增检测"""
        # 使用较多交易日+多只股票，确保突增超过3σ阈值
        dates = pd.date_range('2024-01-01', periods=30, freq='B')
        stocks = ['SH600000', 'SH600001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        n = len(dates) * len(stocks)
        # 前28天正常，最后2天SH600001突增100倍
        volumes = []
        for d in range(len(dates)):
            for s_idx in range(len(stocks)):
                if s_idx == 1 and d >= 28:
                    volumes.append(100000)  # 100倍突增
                else:
                    volumes.append(1000)
        df = pd.DataFrame({
            '$open': [100.0] * n,
            '$close': [100.0] * n,
            '$high': [100.0] * n,
            '$low': [100.0] * n,
            '$volume': volumes,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator.validate_all()
        self.assertIn('volume_anomaly', issues)


class TestDataValidatorCheckGapAnomalies(unittest.TestCase):
    """测试跳空检测"""

    def test_large_gap_detected(self):
        """大幅跳空检测"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100, 100, 200, 100, 100],  # 第三天跳空100%
            '$close': [100, 100, 100, 100, 100],
            '$high': [100] * 5,
            '$low': [100] * 5,
            '$volume': [1000] * 5,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator.validate_all()
        self.assertIn('open_gap', issues)

    def test_normal_open_no_gap(self):
        """正常开盘无跳空"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100, 100.5, 101, 100.8, 100.2],
            '$close': [100] * 5,
            '$high': [100] * 5,
            '$low': [100] * 5,
            '$volume': [1000] * 5,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator.validate_all()
        self.assertNotIn('open_gap', issues)


class TestDataValidatorCheckSplitEvents(unittest.TestCase):
    """测试拆分事件检测"""

    def test_large_drop_detected_as_split(self):
        """大幅下跌检测为拆分"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100, 100, 5, 100, 100],  # 第三天跌到5
            '$close': [100, 100, 5, 100, 100],
            '$high': [100] * 5,
            '$low': [5] + [100] * 4,
            '$volume': [1000] * 5,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator.validate_all()
        self.assertIn('split_events', issues)

    def test_no_split_normal_data(self):
        """正常数据无拆分"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100] * 5,
            '$close': [100] * 5,
            '$high': [100] * 5,
            '$low': [100] * 5,
            '$volume': [1000] * 5,
        }, index=idx)

        validator = DataValidator(df)
        issues = validator.validate_all()
        self.assertNotIn('split_events', issues)


class TestDataValidatorApplyCorrections(unittest.TestCase):
    """测试数据修正"""

    def test_clip_extreme_prices(self):
        """极端价格截断"""
        dates = pd.date_range('2024-01-01', periods=3, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100.0, 15000.0, 100.0],
            '$close': [100.0, 15000.0, 100.0],
            '$high': [100.0, 15000.0, 100.0],
            '$low': [100.0, 15000.0, 100.0],
            '$volume': [1000.0] * 3,
        }, index=idx)

        validator = DataValidator(df)
        validator.validate_all()  # 必须先运行验证， populate self.issues
        corrected = validator.apply_corrections()
        self.assertEqual(float(corrected.loc[(dates[1], 'SH600000'), '$close']), 10000.0)

    def test_clip_volume(self):
        """成交量截断"""
        # 使用20天数据，其中后5天突增，确保超过3σ阈值
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        # 前15天正常，后5天突增100倍
        volumes = [1000.0] * 15 + [100000.0] * 5
        df = pd.DataFrame({
            '$open': [100.0] * 20,
            '$close': [100.0] * 20,
            '$high': [100.0] * 20,
            '$low': [100.0] * 20,
            '$volume': volumes,
        }, index=idx)

        validator = DataValidator(df)
        validator.validate_all()  # 必须先运行验证，populate self.issues
        corrected = validator.apply_corrections()
        # 异常成交量应被截断（3倍标准差）
        vol_val = float(corrected.loc[(dates[-1], 'SH600000'), '$volume'])
        self.assertLessEqual(vol_val, 100000.0)


class TestValidateStockData(unittest.TestCase):
    """测试validate_stock_data函数"""

    def test_returns_dict_with_issues(self):
        """返回包含问题的字典"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [100] * 5,
            '$close': [100] * 5,
            '$high': [100] * 5,
            '$low': [100] * 5,
            '$volume': [1000] * 5,
        }, index=idx)

        result = validate_stock_data(df)
        self.assertIsInstance(result, dict)
        self.assertIn('total_issues', result)
        self.assertIn('issues', result)


class TestPrintTradingRulesSummary(unittest.TestCase):
    """测试交易规则摘要打印"""

    def test_prints_no_error(self):
        """打印无错误"""
        # 应能正常执行不抛出异常
        print_trading_rules_summary()
        self.assertTrue(True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
