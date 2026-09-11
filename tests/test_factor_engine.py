#!/usr/bin/env python3
"""
因子引擎详细测试
================
测试 engine/factor.py 的所有功能。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from engine.factor import FactorEngine, create_factor_engine


class TestFactorEngineNormalizeIndex(unittest.TestCase):
    """测试索引标准化"""

    def setUp(self):
        self.engine = create_factor_engine()

    def test_normalize_standard_index(self):
        """标准索引"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        series = pd.Series(np.random.rand(10), index=idx)

        result = self.engine._normalize_index(series)
        self.assertEqual(result.index.names, ['datetime', 'instrument'])

    def test_normalize_none_names(self):
        """None名称索引"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks])  # 无名称
        series = pd.Series(np.random.rand(10), index=idx)

        result = self.engine._normalize_index(series)
        self.assertEqual(result.index.names, ['datetime', 'instrument'])

    def test_normalize_instrument_date_names(self):
        """(instrument, date) 顺序的索引"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([stocks, dates], names=['instrument', 'date'])
        series = pd.Series(np.random.rand(10), index=idx)

        result = self.engine._normalize_index(series)
        self.assertEqual(result.index.names, ['datetime', 'instrument'])
        # 验证交换正确
        self.assertTrue(result.index[0][0] == dates[0])
        self.assertTrue(result.index[0][1] == stocks[0])

    def test_normalize_string_ticker_first(self):
        """股票代码在前（以SH/SZ/BJ开头）"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([stocks, dates])  # 无名称
        series = pd.Series(np.random.rand(10), index=idx)

        result = self.engine._normalize_index(series)
        self.assertEqual(result.index.names, ['datetime', 'instrument'])
        # 股票代码应移到最后
        self.assertTrue(result.index[0][1].startswith(('SH', 'SZ', 'BJ')))


class TestFactorEngineLoadFactor(unittest.TestCase):
    """测试因子加载"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_factor_engine(workspace=Path(self.tmpdir.name))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_factor_success(self):
        """成功加载因子"""
        factor_dir = Path(self.tmpdir.name) / 'test_factor'
        factor_dir.mkdir()
        
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({'10-day Momentum': np.random.rand(20)}, index=idx)
        df.to_hdf(factor_dir / 'result.h5', key='data', mode='w')

        result = self.engine.load_factor('test_factor')
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 20)
        self.assertEqual(result.index.names, ['datetime', 'instrument'])

    def test_load_factor_missing(self):
        """缺失因子文件"""
        result = self.engine.load_factor('nonexistent')
        self.assertIsNone(result)

    def test_load_factor_empty_file(self):
        """空文件"""
        factor_dir = Path(self.tmpdir.name) / 'empty_factor'
        factor_dir.mkdir()
        # 创建空h5文件
        pd.DataFrame().to_hdf(factor_dir / 'result.h5', key='data', mode='w')

        result = self.engine.load_factor('empty_factor')
        self.assertIsNone(result)

    def test_load_factors_batch(self):
        """批量加载因子"""
        # 创建两个因子
        for fname in ['factor_a', 'factor_b']:
            factor_dir = Path(self.tmpdir.name) / fname
            factor_dir.mkdir()
            dates = pd.date_range('2024-01-01', periods=5, freq='B')
            stocks = ['SH600000']
            idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
            df = pd.DataFrame({'value': np.random.rand(5)}, index=idx)
            df.to_hdf(factor_dir / 'result.h5', key='data', mode='w')

        result = self.engine.load_factors(['factor_a', 'factor_b'])
        self.assertEqual(len(result), 2)
        self.assertIn('factor_a', result)
        self.assertIn('factor_b', result)

    def test_load_factors_with_missing(self):
        """部分缺失的批量加载"""
        factor_dir = Path(self.tmpdir.name) / 'factor_a'
        factor_dir.mkdir()
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({'value': np.random.rand(5)}, index=idx)
        df.to_hdf(factor_dir / 'result.h5', key='data', mode='w')

        result = self.engine.load_factors(['factor_a', 'missing_factor'])
        self.assertEqual(len(result), 1)
        self.assertIn('factor_a', result)


class TestFactorEngineComputeIC(unittest.TestCase):
    """测试IC计算"""

    def setUp(self):
        self.engine = create_factor_engine()

    def test_compute_ic_perfect_positive(self):
        """完全正相关"""
        n = 200
        idx = pd.MultiIndex.from_tuples([(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)])
        factor = pd.Series(np.arange(n), index=idx)
        returns = pd.Series(np.arange(n).astype(float), index=idx)

        ic = self.engine.compute_ic(factor, returns)
        self.assertAlmostEqual(ic, 1.0, places=5)

    def test_compute_ic_perfect_negative(self):
        """完全负相关"""
        n = 200
        idx = pd.MultiIndex.from_tuples([(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)])
        factor = pd.Series(np.arange(n), index=idx)
        returns = pd.Series(np.arange(n, 0, -1).astype(float), index=idx)

        ic = self.engine.compute_ic(factor, returns)
        self.assertAlmostEqual(ic, -1.0, places=5)

    def test_compute_ic_insufficient_data(self):
        """数据不足返回NaN"""
        n = 50  # 少于100
        idx = pd.MultiIndex.from_tuples([(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)])
        factor = pd.Series(np.random.rand(n), index=idx)
        returns = pd.Series(np.random.rand(n), index=idx)

        ic = self.engine.compute_ic(factor, returns)
        self.assertTrue(np.isnan(ic))

    def test_compute_ic_with_nan(self):
        """含NaN数据"""
        n = 200
        idx = pd.MultiIndex.from_tuples([(pd.Timestamp('2024-01-01'), f'SH{i:06d}') for i in range(n)])
        factor = pd.Series(np.random.rand(n), index=idx)
        factor[::10] = np.nan  # 每10个设一个NaN
        returns = pd.Series(np.random.rand(n), index=idx)

        ic = self.engine.compute_ic(factor, returns)
        self.assertIsInstance(ic, float)
        self.assertGreaterEqual(ic, -1)
        self.assertLessEqual(ic, 1)


class TestFactorEngineComputeICTimeSeries(unittest.TestCase):
    """测试时间序列IC计算"""

    def setUp(self):
        self.engine = create_factor_engine()

    def test_compute_ic_time_series(self):
        """时间序列IC"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = [f'SH{i:06d}' for i in range(100)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        
        factor = pd.Series(np.random.rand(1000), index=idx)
        returns = pd.Series(np.random.rand(1000), index=idx)

        ic_by_date = self.engine.compute_ic_time_series(factor, returns)
        self.assertEqual(len(ic_by_date), 10)  # 10个交易日

    def test_compute_ic_time_series_insufficient_stocks(self):
        """每日股票数不足"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = [f'SH{i:06d}' for i in range(30)]  # 少于50
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        
        factor = pd.Series(np.random.rand(150), index=idx)
        returns = pd.Series(np.random.rand(150), index=idx)

        ic_by_date = self.engine.compute_ic_time_series(factor, returns)
        self.assertEqual(len(ic_by_date), 0)


class TestFactorEngineSynthesizeFactors(unittest.TestCase):
    """测试因子合成"""

    def setUp(self):
        self.engine = create_factor_engine()

    def test_synthesize_equal_weight(self):
        """等权合成"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])

        factors = {
            'f1': pd.Series(list(range(1, 11)), index=idx),
            'f2': pd.Series(list(range(10, 0, -1)), index=idx),
        }

        result = self.engine.synthesize_factors(factors)
        self.assertIsInstance(result, pd.Series)
        self.assertEqual(len(result), 10)

    def test_synthesize_weighted(self):
        """加权合成"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])

        factors = {
            'f1': pd.Series(list(range(1, 11)), index=idx),
            'f2': pd.Series(list(range(10, 0, -1)), index=idx),
        }
        weights = {'f1': 0.7, 'f2': 0.3}

        result = self.engine.synthesize_factors(factors, weights)
        self.assertIsInstance(result, pd.Series)

    def test_synthesize_empty(self):
        """空因子"""
        result = self.engine.synthesize_factors({})
        self.assertEqual(len(result), 0)

    def test_synthesize_with_nan(self):
        """含NaN因子"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])

        # 5个值（5天×1只股票），第1个为NaN
        values = [np.nan, 2.0, 3.0, 4.0, 5.0]
        factors = {
            'f1': pd.Series(values, index=idx),
        }

        result = self.engine.synthesize_factors(factors)
        self.assertFalse(result.isna().all())  # ffill后不应全NaN


class TestFactorEngineGetTopStocks(unittest.TestCase):
    """测试Top股票选取"""

    def setUp(self):
        self.engine = create_factor_engine()

    def test_get_top_stocks_series(self):
        """Series输入"""
        dates = pd.date_range('2024-01-01', periods=3, freq='B')
        stocks = [f'SH{i:06d}' for i in range(10)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        scores = pd.Series(np.random.rand(30), index=idx)
        
        result = self.engine.get_top_stocks(scores, top_k=5, date=dates[2])
        self.assertEqual(len(result), 5)
        self.assertIn('score', result.columns)
        self.assertIn('rank', result.columns)
        self.assertEqual(list(result['rank']), [1, 2, 3, 4, 5])

    def test_get_top_stocks_dataframe(self):
        """DataFrame输入"""
        dates = pd.date_range('2024-01-01', periods=3, freq='B')
        stocks = [f'SH{i:06d}' for i in range(10)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        
        df = pd.DataFrame({
            'f1': np.random.rand(30),
            'f2': np.random.rand(30),
        }, index=idx)
        
        result = self.engine.get_top_stocks(df, top_k=5, date=dates[2])
        self.assertEqual(len(result), 5)

    def test_get_top_stocks_default_date(self):
        """默认使用最新日期"""
        dates = pd.date_range('2024-01-01', periods=3, freq='B')
        stocks = [f'SH{i:06d}' for i in range(10)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        scores = pd.Series(np.random.rand(30), index=idx)
        
        result = self.engine.get_top_stocks(scores, top_k=5)
        # 应使用最新日期 dates[2]
        self.assertEqual(len(result), 5)

    def test_get_top_stocks_insufficient_stocks(self):
        """股票数不足"""
        dates = pd.date_range('2024-01-01', periods=1, freq='B')
        stocks = ['SH600000']  # 只有1只
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        scores = pd.Series([0.5], index=idx)
        
        result = self.engine.get_top_stocks(scores, top_k=5)
        self.assertEqual(len(result), 1)  # 只能选1只


class TestFactorEngineComputeFactorICSummary(unittest.TestCase):
    """测试因子IC汇总"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_factor_engine(workspace=Path(self.tmpdir.name))
        
        # 创建测试因子
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        stocks = [f'SH{i:06d}' for i in range(100)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        
        for i in range(3):
            factor_dir = Path(self.tmpdir.name) / f'factor_{i}'
            factor_dir.mkdir()
            values = np.random.rand(2000)
            df = pd.DataFrame({'value': values}, index=idx)
            df.to_hdf(factor_dir / 'result.h5', key='data', mode='w')

        # 创建returns
        self.returns = pd.Series(np.random.rand(2000), index=idx)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_compute_factor_ic_summary(self):
        """因子IC汇总"""
        factor_ids = ['factor_0', 'factor_1', 'factor_2']
        result = self.engine.compute_factor_ic_summary(factor_ids, self.returns)
        
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 3)
        self.assertIn('IC_5d', result.columns)
        self.assertIn('IC_t_5d', result.columns)
        self.assertIn('IC_pos_5d', result.columns)

    def test_compute_factor_ic_summary_with_missing(self):
        """含缺失因子的汇总"""
        factor_ids = ['factor_0', 'missing_factor']
        result = self.engine.compute_factor_ic_summary(factor_ids, self.returns)
        
        self.assertEqual(len(result), 1)  # 只返回存在的因子


if __name__ == '__main__':
    unittest.main(verbosity=2)
