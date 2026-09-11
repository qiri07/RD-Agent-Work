#!/usr/bin/env python3
"""
定价引擎详细测试
================
测试 engine/pricing.py 的所有功能，包括拆分检测。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import tempfile

from engine.pricing import PriceEngine


class TestPriceEngineSplitDetection(unittest.TestCase):
    """测试拆分检测功能"""

    def test_detect_split_events_basic(self):
        """基本拆分检测 — 需要至少5只股票同天拆分才认为是批量事件"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = [f'SH{i:06d}' for i in range(10)]  # 10只股票
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': np.ones(len(idx)) * 10,
            '$close': np.ones(len(idx)) * 10,
            '$high': np.ones(len(idx)) * 10,
            '$low': np.ones(len(idx)) * 10,
            '$volume': np.ones(len(idx)) * 1000,
        }, index=idx)

        # 在2024-01-08制造拆分（价格从10涨到100，相当于10倍拆分）
        split_date = pd.Timestamp('2024-01-08')
        mask = df.index.get_level_values('datetime') == split_date
        df.loc[mask, '$close'] = 100
        df.loc[mask, '$open'] = 100
        df.loc[mask, '$high'] = 100
        df.loc[mask, '$low'] = 100

        engine = PriceEngine()
        events = engine._detect_split_events(df)
        self.assertGreater(len(events), 0)

    def test_detect_split_events_no_split(self):
        """无拆分数据"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = ['SH600000', 'SZ000001']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': np.arange(len(idx)) * 10 + 10,
            '$close': np.arange(len(idx)) * 10 + 11,
            '$high': np.arange(len(idx)) * 10 + 12,
            '$low': np.arange(len(idx)) * 10 + 9,
            '$volume': np.ones(len(idx)) * 1000,
        }, index=idx)

        engine = PriceEngine()
        events = engine._detect_split_events(df)
        self.assertEqual(len(events), 0)

    def test_compute_adjusted_prices_with_split(self):
        """有拆分时的复权"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = [f'SH{i:06d}' for i in range(10)]  # 至少5只才能触发批量检测
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        n = len(idx)
        df = pd.DataFrame({
            '$open': [10.0] * n,
            '$close': [10.0] * n,
            '$high': [10.0] * n,
            '$low': [10.0] * n,
            '$volume': [1000] * n,
        }, index=idx)

        # 最后一天的所有股票价格涨到100（模拟拆分）
        split_date = dates[-1]
        mask = df.index.get_level_values('datetime') == split_date
        df.loc[mask, '$close'] = 100.0
        df.loc[mask, '$open'] = 100.0
        df.loc[mask, '$high'] = 100.0
        df.loc[mask, '$low'] = 100.0

        engine = PriceEngine()
        adj, splits = engine.compute_adjusted_prices(df)

        # 应有拆分被检测到
        self.assertGreater(len(splits), 0)
        # 复权后价格应发生变化
        self.assertNotEqual(adj['$close'].tolist(), df['$close'].tolist())

    def test_compute_adjusted_prices_no_split(self):
        """无拆分时价格不变"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': np.arange(len(idx)) * 10 + 10,
            '$close': np.arange(len(idx)) * 10 + 11,
            '$high': np.arange(len(idx)) * 10 + 12,
            '$low': np.arange(len(idx)) * 10 + 9,
            '$volume': [1000] * 10,
        }, index=idx)

        engine = PriceEngine()
        adj, splits = engine.compute_adjusted_prices(df)

        # 无拆分
        self.assertEqual(len(splits), 0)
        # 价格应保持不变
        pd.testing.assert_frame_equal(adj, df)

    def test_compute_adjusted_prices_default_source(self):
        """使用默认数据源"""
        engine = PriceEngine()
        # 不应抛出异常
        adj, splits = engine.compute_adjusted_prices()
        self.assertIsNotNone(adj)
        self.assertIsInstance(splits, list)

    def test_detect_split_events_batch_event(self):
        """批量拆分事件检测"""
        # 创建多只股票在同一日期拆分的数据
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = [f'SH{i:06d}' for i in range(10)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': np.ones(len(idx)) * 10,
            '$close': np.ones(len(idx)) * 10,
            '$high': np.ones(len(idx)) * 10,
            '$low': np.ones(len(idx)) * 10,
            '$volume': np.ones(len(idx)) * 1000,
        }, index=idx)

        # 在多个股票上制造拆分
        split_date = pd.Timestamp('2024-01-08')
        mask = df.index.get_level_values('datetime') == split_date
        df.loc[mask, '$close'] = 100  # 10倍拆分

        engine = PriceEngine()
        events = engine._detect_split_events(df)

        # 应检测到批量拆分
        self.assertGreater(len(events), 0)

    def test_split_ratio_threshold(self):
        """阈值测试"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [10] * 10,
            '$close': [10] * 9 + [15],  # 只涨50%，低于阈值
            '$high': [10] * 10,
            '$low': [10] * 10,
            '$volume': [1000] * 10,
        }, index=idx)

        engine = PriceEngine(split_ratio_threshold=3.0)
        events = engine._detect_split_events(df)

        # 50%涨幅不应触发拆分检测
        self.assertEqual(len(events), 0)


class TestPriceEngineLoadPrices(unittest.TestCase):
    """测试价格加载"""

    def test_load_prices_from_parquet(self):
        """从parquet加载"""
        with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as f:
            tmp_path = Path(f.name)
            dates = pd.date_range('2024-01-01', periods=5, freq='B')
            stocks = ['SH600000', 'SZ000001']
            idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
            df = pd.DataFrame({
                '$open': np.random.rand(len(idx)) * 100 + 10,
                '$close': np.random.rand(len(idx)) * 100 + 10,
                '$high': np.random.rand(len(idx)) * 100 + 10,
                '$low': np.random.rand(len(idx)) * 100 + 10,
                '$volume': np.random.rand(len(idx)) * 10000,
            }, index=idx)
            df.to_parquet(tmp_path)

        try:
            engine = PriceEngine(source_pq=tmp_path)
            prices = engine.load_prices()
            self.assertEqual(prices.index.names, ['datetime', 'instrument'])
            self.assertEqual(len(prices), len(df))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_load_prices_removes_duplicates(self):
        """去除重复索引"""
        with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as f:
            tmp_path = Path(f.name)
            dates = pd.date_range('2024-01-01', periods=3, freq='B')
            stocks = ['SH600000']
            idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
            # 创建重复索引
            df = pd.DataFrame({
                '$open': [10, 10, 10, 11],
                '$close': [10, 10, 10, 11],
                '$high': [10, 10, 10, 11],
                '$low': [10, 10, 10, 11],
                '$volume': [1000] * 4,
            }, index=idx.append(idx[:1]))  # 追加第一行制造重复
            df.to_parquet(tmp_path)

        try:
            engine = PriceEngine(source_pq=tmp_path)
            prices = engine.load_prices()
            # 应去重
            self.assertEqual(len(prices), 3)
        finally:
            tmp_path.unlink(missing_ok=True)


class TestPriceEngineBuildPriceMap(unittest.TestCase):
    """测试价格映射构建"""

    def test_build_price_map_with_all_columns(self):
        """包含所有列的价格映射"""
        engine = PriceEngine()
        dates = pd.date_range('2024-01-01', periods=3, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [10, 11, 12],
            '$close': [10.5, 11.5, 12.5],
            '$high': [11, 12, 13],
            '$low': [9, 10, 11],
            '$volume': [1000, 1100, 1200],
        }, index=idx)

        price_map = engine.build_price_map(df)
        self.assertEqual(len(price_map), 3)

        # 检查结构
        key = (dates[0], 'SH600000')
        self.assertIn(key, price_map)
        self.assertEqual(price_map[key]['open'], 10)
        self.assertEqual(price_map[key]['close'], 10.5)
        self.assertEqual(price_map[key]['high'], 11)
        self.assertEqual(price_map[key]['low'], 9)

    def test_build_price_map_missing_columns(self):
        """缺少high/low列时使用close"""
        engine = PriceEngine()
        dates = pd.date_range('2024-01-01', periods=2, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({
            '$open': [10, 11],
            '$close': [10.5, 11.5],
            '$volume': [1000, 1100],
        }, index=idx)

        price_map = engine.build_price_map(df)
        key = (dates[0], 'SH600000')
        self.assertEqual(price_map[key]['high'], 10.5)  # 使用close
        self.assertEqual(price_map[key]['low'], 10.5)


class TestPriceEngineGetStockPrices(unittest.TestCase):
    """测试获取股票价格"""

    def test_get_stock_prices_with_dates(self):
        """带日期范围的价格获取"""
        engine = PriceEngine()
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({'$close': np.arange(100, 110)}, index=idx)

        prices = engine.get_stock_prices(df, 'SH600000',
                                         start_date=dates[2],
                                         end_date=dates[5])
        self.assertEqual(len(prices), 4)
        self.assertEqual(prices.index[0], dates[2])
        self.assertEqual(prices.index[-1], dates[5])

    def test_get_stock_prices_without_dates(self):
        """不带日期范围"""
        engine = PriceEngine()
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({'$close': np.arange(100, 110)}, index=idx)

        prices = engine.get_stock_prices(df, 'SH600000')
        self.assertEqual(len(prices), 10)


class TestPriceEngineGetReturns(unittest.TestCase):
    """测试收益计算"""

    def test_get_returns_basic(self):
        """基本收益计算"""
        engine = PriceEngine()
        dates = pd.date_range('2024-01-01', periods=15, freq='B')
        stocks = [f'SH{i:06d}' for i in range(3)]  # 至少3只，避免xs返回DataFrame
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        # 每只股票15个价格，共45行
        close_vals = [float(i) for i in range(100, 115) for _ in stocks]
        df = pd.DataFrame({'$close': close_vals}, index=idx)

        returns = engine.get_returns(df, 'SH000000', hold_days=5)
        self.assertGreater(len(returns), 0)
        # 5日收益应为正（递增价格）
        self.assertGreater(float(returns.iloc[0]), 0)

    def test_get_returns_insufficient_data(self):
        """数据不足时返回空序列"""
        engine = PriceEngine()
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        stocks = ['SH600000']
        idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
        df = pd.DataFrame({'$close': [100, 101, 102, 103, 104]}, index=idx)

        returns = engine.get_returns(df, 'SH600000', hold_days=5)
        self.assertEqual(len(returns), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
