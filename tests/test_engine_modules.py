#!/usr/bin/env python3
"""
引擎模块测试
============
测试 engine/ 下的所有核心模块。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.pricing import PriceEngine
from engine.backtest import BacktestEngine, create_backtest_engine, BacktestResult
from engine.factor import FactorEngine, create_factor_engine
from engine.metrics import PerformanceAnalyzer, create_performance_analyzer, PerformanceMetrics
from engine.cache import CacheManager, get_cache, clear_global_cache, load_cached_parquet


class TestPriceEngine(unittest.TestCase):
    """测试价格引擎"""
    
    def test_init_default_source(self):
        """默认数据源初始化"""
        engine = PriceEngine()
        self.assertIsNotNone(engine.source_pq)
    
    def test_init_custom_source(self):
        """自定义数据源初始化"""
        with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as f:
            tmp_path = Path(f.name)
        
        try:
            engine = PriceEngine(source_pq=tmp_path)
            self.assertEqual(engine.source_pq, tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    
    def test_load_prices_empty(self):
        """空文件加载测试"""
        with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as f:
            tmp_path = Path(f.name)
            # 创建空DataFrame
            pd.DataFrame().to_parquet(tmp_path)
        
        try:
            engine = PriceEngine(source_pq=tmp_path)
            # 空DataFrame时load_prices会抛出异常，预期行为
            with self.assertRaises((ValueError, Exception)):
                engine.load_prices()
        finally:
            tmp_path.unlink(missing_ok=True)
    
    def test_build_price_map(self):
        """构建价格映射"""
        engine = PriceEngine()
        
        # 创建测试数据
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': np.random.rand(len(idx)) * 100 + 10,
            '$close': np.random.rand(len(idx)) * 100 + 10,
            '$high': np.random.rand(len(idx)) * 100 + 10,
            '$low': np.random.rand(len(idx)) * 100 + 10,
        }, index=idx)
        
        price_map = engine.build_price_map(df)
        
        self.assertEqual(len(price_map), len(df))
        for (dt, stock), row in df.iterrows():
            key = (dt, stock)
            self.assertIn(key, price_map)
            self.assertEqual(price_map[key]['close'], row['$close'])
    
    def test_get_stock_prices(self):
        """获取股票价格序列"""
        engine = PriceEngine()
        
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({'$close': np.arange(100, 110)}, index=idx)
        
        prices = engine.get_stock_prices(df, 'SH600000')
        self.assertEqual(len(prices), 10)
    
    def test_get_returns(self):
        """计算收益序列"""
        engine = PriceEngine()
        
        dates = pd.date_range('2024-01-01', periods=15, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({'$close': np.arange(100, 115)}, index=idx)
        
        returns = engine.get_returns(df, 'SH600000', hold_days=5)
        self.assertGreater(len(returns), 0)


class TestBacktestEngine(unittest.TestCase):
    """测试回测引擎"""
    
    def test_init_default_params(self):
        """默认参数初始化"""
        engine = create_backtest_engine()
        self.assertEqual(engine.initial_capital, 1_000_000)
        self.assertEqual(engine.commission_rate, 0.0003)
        self.assertEqual(engine.slippage_rate, 0.001)
    
    def test_init_custom_params(self):
        """自定义参数初始化"""
        engine = create_backtest_engine(
            initial_capital=2_000_000,
            commission_rate=0.0005
        )
        self.assertEqual(engine.initial_capital, 2_000_000)
        self.assertEqual(engine.commission_rate, 0.0005)
    
    def test_run_empty_data(self):
        """空数据运行测试"""
        engine = create_backtest_engine()
        result = engine.run([], {}, {}, hold_days=5, top_k=10)
        
        self.assertIsInstance(result, BacktestResult)
        self.assertEqual(len(result.daily_value), 0)
        self.assertEqual(len(result.trades), 0)
    
    def test_run_with_signals(self):
        """带信号回测"""
        engine = create_backtest_engine(initial_capital=1_000_000)
        
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        
        signals = {i: ['SH600000'] for i in range(0, len(dates), 5)}
        
        result = engine.run(dates, price_map, signals, hold_days=5, top_k=1)
        
        self.assertIsInstance(result, BacktestResult)
        self.assertGreater(len(result.daily_value), 0)
    
    def test_run_fixed_hold(self):
        """固定持仓回测"""
        engine = create_backtest_engine(initial_capital=1_000_000)
        
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        
        result = engine.run_fixed_hold(dates, price_map, ['SH600000'], hold_days=0)
        
        self.assertIsInstance(result, BacktestResult)
    
    def test_result_dataclass(self):
        """结果数据类测试"""
        result = BacktestResult(
            daily_value=[{'date': '2024-01-01', 'value': 1000000}],
            trades=[{'date': '2024-01-01', 'action': 'BUY'}]
        )
        
        self.assertEqual(len(result.daily_value), 1)
        self.assertEqual(len(result.trades), 1)


class TestFactorEngine(unittest.TestCase):
    """测试因子引擎"""
    
    def test_init_default_workspace(self):
        """默认工作空间初始化"""
        engine = create_factor_engine()
        self.assertIsNotNone(engine.workspace)
    
    def test_init_custom_workspace(self):
        """自定义工作空间初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = FactorEngine(workspace=Path(tmpdir))
            self.assertEqual(engine.workspace, Path(tmpdir))
    
    def test_load_factor_missing(self):
        """缺失因子文件测试"""
        engine = create_factor_engine()
        result = engine.load_factor('nonexistent_factor')
        self.assertIsNone(result)
    
    def test_normalize_index(self):
        """索引标准化测试"""
        engine = create_factor_engine()
        
        # 测试标准索引
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        series = pd.Series(np.random.rand(10), index=idx)
        
        normalized = engine._normalize_index(series)
        self.assertEqual(normalized.index.names, ['datetime', 'instrument'])
    
    def test_cross_section_zscore(self):
        """横截面标准化测试"""
        engine = create_factor_engine()
        
        dates = pd.date_range('2024-01-01', periods=3, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({'factor_a': np.random.rand(6)}, index=idx)
        
        result = engine.cross_section_zscore(df)
        self.assertEqual(result.shape, df.shape)
        
        # 每天的标准化均值应接近0
        for date in dates:
            day_data = result.xs(date, level='datetime')['factor_a']
            self.assertAlmostEqual(day_data.mean(), 0, places=5)
    
    def test_compute_ic(self):
        """IC计算测试"""
        engine = create_factor_engine()
        
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        stocks = [f'SH{i:06d}' for i in range(100)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        
        factor = pd.Series(np.random.rand(2000), index=idx)
        returns = pd.Series(np.random.rand(2000), index=idx)
        
        ic = engine.compute_ic(factor, returns)
        self.assertIsInstance(ic, float)
        self.assertGreaterEqual(ic, -1)
        self.assertLessEqual(ic, 1)
    
    def test_synthesize_factors(self):
        """因子合成测试"""
        engine = create_factor_engine()
        
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        
        # 使用Series字典而不是DataFrame
        factors = {
            'factor_a': pd.Series(np.random.rand(10), index=idx),
            'factor_b': pd.Series(np.random.rand(10), index=idx)
        }
        
        weights = {'factor_a': 0.6, 'factor_b': 0.4}
        result = engine.synthesize_factors(factors, weights)
        
        self.assertIsInstance(result, pd.Series)
        self.assertEqual(len(result), 10)


class TestPerformanceAnalyzer(unittest.TestCase):
    """测试绩效分析器"""
    
    def test_init_default(self):
        """默认初始化"""
        analyzer = create_performance_analyzer()
        self.assertEqual(analyzer.initial_capital, 1_000_000)
    
    def test_analyze_empty(self):
        """空数据测试"""
        analyzer = create_performance_analyzer()
        result = analyzer.analyze([], [])
        
        self.assertIsInstance(result, PerformanceMetrics)
        self.assertEqual(result.total_days, 0)
        self.assertEqual(result.total_return_pct, 0)
    
    def test_analyze_single_day(self):
        """单日数据测试"""
        analyzer = create_performance_analyzer()
        
        daily_value = [
            {'date': '2024-01-01', 'value': 1_000_000, 'cash': 1_000_000, 'positions': 0}
        ]
        
        result = analyzer.analyze(daily_value, [])
        self.assertIsInstance(result, PerformanceMetrics)
    
    def test_analyze_with_trades(self):
        """带交易数据测试"""
        analyzer = create_performance_analyzer()
        
        daily_value = [
            {'date': pd.Timestamp('2024-01-01'), 'value': 1_000_000, 'cash': 1_000_000, 'positions': 0},
            {'date': pd.Timestamp('2024-01-02'), 'value': 1_050_000, 'cash': 500_000, 'positions': 1},
            {'date': pd.Timestamp('2024-01-03'), 'value': 1_100_000, 'cash': 0, 'positions': 0},
        ]
        
        trades = [
            {'date': pd.Timestamp('2024-01-02'), 'action': 'BUY', 'stock': 'SH600000', 'pnl_pct': 0},
            {'date': pd.Timestamp('2024-01-03'), 'action': 'SELL', 'stock': 'SH600000', 'pnl_pct': 10},
        ]
        
        result = analyzer.analyze(daily_value, trades)
        
        self.assertGreater(result.total_return_pct, 0)
        # total_trades是SELL交易数量
        self.assertEqual(result.total_trades, 1)
    
    def test_generate_report(self):
        """报告生成测试"""
        analyzer = create_performance_analyzer()
        
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
        
        report = analyzer.generate_report(metrics, "Test Strategy")
        
        self.assertIn("Test Strategy", report)
        self.assertIn("15.50%", report)
        self.assertIn("1.500", report)


class TestCacheManager(unittest.TestCase):
    """测试缓存管理器"""
    
    def test_init(self):
        """初始化测试"""
        cache = CacheManager(max_size_mb=500)
        self.assertEqual(cache.max_size_mb, 500)
    
    def test_set_get(self):
        """设置和获取测试"""
        cache = CacheManager()
        cache.set('key1', 'value1')
        self.assertEqual(cache.get('key1'), 'value1')
    
    def test_get_missing(self):
        """获取不存在的key"""
        cache = CacheManager()
        self.assertIsNone(cache.get('missing_key'))
    
    def test_clear(self):
        """清除缓存测试"""
        cache = CacheManager()
        cache.set('key1', 'value1')
        cache.clear()
        self.assertIsNone(cache.get('key1'))
    
    def test_global_cache(self):
        """全局缓存测试"""
        clear_global_cache()
        cache = get_cache()
        self.assertIsInstance(cache, CacheManager)


if __name__ == '__main__':
    unittest.main(verbosity=2)
