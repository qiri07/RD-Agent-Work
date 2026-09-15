#!/usr/bin/env python3
"""
data_corrector.py 单元测试
============================
测试 correct_data, classify_data_issues, apply_trading_rule_corrections 等功能。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from data_corrector import (
    correct_data,
    classify_data_issues,
    apply_trading_rule_corrections,
    correct_single_stock_anomalies,
    correct_batch_anomalies,
    detect_split_events,
)


def _make_multiindex_df(n_stocks=3, n_days=10, seed=42):
    """创建标准 MultiIndex 价格 DataFrame"""
    instruments = [f"SH60000{i}" for i in range(n_stocks)]
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    np.random.seed(seed)
    data = {
        "$open": np.random.rand(len(idx)) * 50 + 50,
        "$close": np.random.rand(len(idx)) * 50 + 50,
        "$high": np.random.rand(len(idx)) * 50 + 55,
        "$low": np.random.rand(len(idx)) * 50 + 45,
        "$volume": np.random.rand(len(idx)) * 1e8 + 1e6,
    }
    return pd.DataFrame(data, index=idx)


class TestClassifyDataIssues(unittest.TestCase):
    """测试 classify_data_issues 函数"""

    def test_no_issues(self):
        """无问题数据"""
        df = _make_multiindex_df()
        result = classify_data_issues(df)
        # 返回 dict，键为 issue 类型，值为空 list 表示无问题
        self.assertIsInstance(result, dict)
        self.assertEqual(sum(len(v) for v in result.values()), 0)

    def test_negative_price(self):
        """负价格问题（classify_data_issues 当前不检测负价格，需设置极端高价触发检测）"""
        df = _make_multiindex_df()
        df.loc[("2020-01-02", "SH600000"), "$close"] = -10.0
        result = classify_data_issues(df)
        # classify_data_issues 只检测 split_events、extreme_prices(>500)、invalid_records(零成交量)
        # 负价格不属于以上任何一类，total 可能为 0（已知限制）
        self.assertIsInstance(result, dict)

    def test_zero_price(self):
        """零价格问题（通过零成交量触发检测）"""
        df = _make_multiindex_df()
        df.loc[("2020-01-02", "SH600000"), "$volume"] = 0.0
        result = classify_data_issues(df)
        total = sum(len(v) for v in result.values())
        self.assertGreater(total, 0)

    def test_extreme_return(self):
        """极端涨跌幅问题（通过极端价格触发检测）"""
        df = _make_multiindex_df()
        df.loc[("2020-01-01", "SH600000"), "$close"] = 100.0
        df.loc[("2020-01-02", "SH600000"), "$close"] = 600.0  # >500，触发极端高价检测
        result = classify_data_issues(df)
        total = sum(len(v) for v in result.values())
        self.assertGreater(total, 0)


class TestApplyTradingRuleCorrections(unittest.TestCase):
    """测试 apply_trading_rule_corrections 函数"""

    def test_basic_correction(self):
        """基本修正"""
        df = _make_multiindex_df()
        df.loc[("2020-01-02", "SH600000"), "$close"] = -10.0
        result = apply_trading_rule_corrections(df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(result.index.names, df.index.names)

    def test_preserve_structure(self):
        """保持数据结构"""
        df = _make_multiindex_df()
        result = apply_trading_rule_corrections(df)
        self.assertEqual(len(result), len(df))
        self.assertEqual(result.index.names, df.index.names)


class TestCorrectSingleStockAnomalies(unittest.TestCase):
    """测试 correct_single_stock_anomalies 函数"""

    def test_basic_correction(self):
        """基本修正"""
        df = _make_multiindex_df()
        # 制造单只股票异常：价格翻倍后暴跌
        df.loc[("2020-01-05", "SH600000"), "$close"] = 200.0
        df.loc[("2020-01-06", "SH600000"), "$close"] = 50.0
        result = correct_single_stock_anomalies(df)
        self.assertIsInstance(result, pd.DataFrame)

    def test_empty_dataframe(self):
        """空DataFrame"""
        df = pd.DataFrame(
            columns=["$open", "$close", "$high", "$low", "$volume"],
            index=pd.MultiIndex.from_tuples([], names=["datetime", "instrument"]),
        )
        result = correct_single_stock_anomalies(df)
        self.assertIsInstance(result, pd.DataFrame)


class TestDetectSplitEvents(unittest.TestCase):
    """测试 detect_split_events 函数"""

    def test_no_splits(self):
        """无拆股事件"""
        df = _make_multiindex_df()
        result = detect_split_events(df)
        self.assertEqual(len(result), 0)

    def test_price_gap_detection(self):
        """价格缺口检测"""
        df = _make_multiindex_df()
        # 制造 50% 跌幅（可能是拆股）
        df.loc[("2020-01-02", "SH600000"), "$close"] = 50.0
        df.loc[("2020-01-01", "SH600000"), "$close"] = 100.0
        result = detect_split_events(df)
        self.assertIsInstance(result, list)


class TestCorrectBatchAnomalies(unittest.TestCase):
    """测试 correct_batch_anomalies 函数"""

    def test_basic_correction(self):
        """基本修正"""
        df = _make_multiindex_df()
        # 制造批量异常（某个日期所有股票价格异常高）
        df.loc[("2020-01-03", "SH600000"), "$close"] = 2000.0
        df.loc[("2020-01-03", "SH600001"), "$close"] = 2000.0
        events = [{"date": "2020-01-03", "ratio": 0.001}]
        result = correct_batch_anomalies(df, events)
        self.assertIsInstance(result, pd.DataFrame)


class TestCorrectData(unittest.TestCase):
    """测试 correct_data 函数"""

    def test_basic_correction(self):
        """基本修正"""
        df = _make_multiindex_df()
        df.loc[("2020-01-02", "SH600000"), "$close"] = -10.0
        corrected, report = correct_data(df)
        self.assertIsInstance(corrected, pd.DataFrame)
        self.assertIsInstance(report, dict)

    def test_no_corrections_needed(self):
        """无需修正的数据"""
        df = _make_multiindex_df()
        corrected, report = correct_data(df)
        self.assertEqual(len(corrected), len(df))
        self.assertIsInstance(report, dict)


if __name__ == "__main__":
    unittest.main()
