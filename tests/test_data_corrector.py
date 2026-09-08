#!/usr/bin/env python3
"""
data_corrector.py 单元测试
==========================
测试数据矫正逻辑：拆分检测、批量异常修正、交易规则修正。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from unittest import mock

import config as cfg
from data_corrector import (
    detect_split_events, is_batch_split_event, classify_data_issues,
    correct_batch_anomalies, correct_single_stock_anomalies,
    apply_trading_rule_corrections, correct_data,
)


def _make_price_df(rows):
    """创建测试用的价格 DataFrame (MultiIndex: date, instrument)"""
    data = pd.DataFrame(rows, columns=["date", "instrument", "$open", "$close", "$high", "$low", "$volume", "$factor"])
    data["date"] = pd.to_datetime(data["date"], format="mixed")
    df = data.set_index(["date", "instrument"]).sort_index()
    for c in ["$open", "$close", "$high", "$low", "$volume", "$factor"]:
        if c not in df.columns:
            df[c] = 1.0 if c == "$factor" else 0.0
    return df[["$open", "$close", "$high", "$low", "$volume", "$factor"]]


class TestDetectSplitEvents(unittest.TestCase):
    """测试拆分事件检测"""

    def test_no_split_normal_data(self):
        """正常数据不应检测到拆分"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 10.5, 10.5, 10.6, 10.4, 1100000, 1.0],
            ["2024-01-03", "SH600000", 10.3, 10.3, 10.4, 10.2, 1050000, 1.0],
        ])
        events = detect_split_events(df)
        self.assertEqual(len(events), 0)

    def test_detect_large_drop(self):
        """价格暴跌应检测为拆分事件"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 3.0, 3.0, 3.0, 3.0, 5000000, 1.0],  # 暴跌70%
        ])
        events = detect_split_events(df, ratio_threshold=0.5)
        self.assertGreater(len(events), 0)
        self.assertEqual(events[0]["code"], "SH600000")
        self.assertLess(events[0]["ratio"], 0.5)

    def test_skip_first_day(self):
        """第一天无前收，不应检测"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
        ])
        events = detect_split_events(df)
        self.assertEqual(len(events), 0)

    def test_multiple_stocks(self):
        """多只股票独立检测"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 3.0, 3.0, 3.0, 3.0, 5000000, 1.0],
            ["2024-01-01", "SZ300001", 20.0, 20.0, 20.0, 20.0, 2000000, 1.0],
            ["2024-01-02", "SZ300001", 6.0, 6.0, 6.0, 6.0, 3000000, 1.0],
        ])
        events = detect_split_events(df, ratio_threshold=0.5)
        codes = {e["code"] for e in events}
        self.assertIn("SH600000", codes)
        self.assertIn("SZ300001", codes)

    def test_ratio_boundary(self):
        """刚好在阈值边界的比率不应检测"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 5.1, 5.1, 5.1, 5.1, 1000000, 1.0],  # ratio=0.51 > 0.5
        ])
        events = detect_split_events(df, ratio_threshold=0.5)
        self.assertEqual(len(events), 0)


class TestIsBatchSplitEvent(unittest.TestCase):
    """测试批量拆分事件检测"""

    def test_not_batch(self):
        """少量股票的拆分不是批量事件"""
        events = [
            {"date": "2024-01-02", "code": "SH600000"},
            {"date": "2024-01-02", "code": "SZ300001"},
        ]
        self.assertFalse(is_batch_split_event(events))

    def test_is_batch(self):
        """大量股票同一天拆分为批量事件"""
        events = [{"date": "2024-01-02", "code": f"SH{i:06d}"} for i in range(15)]
        self.assertTrue(is_batch_split_event(events))

    def test_empty_events(self):
        self.assertFalse(is_batch_split_event([]))


class TestClassifyDataIssues(unittest.TestCase):
    """测试数据问题分类"""

    def test_classify_normal_data(self):
        """正常数据应无严重问题"""
        df = _make_price_df([
            ["2024-01-0" + str(d), "SH600000", 10.0, 10.0 + d*0.1, 10.1, 9.9, 1000000, 1.0]
            for d in range(1, 6)
        ])
        issues = classify_data_issues(df)
        self.assertEqual(len(issues["batch_anomalies"]), 0)
        self.assertEqual(len(issues["extreme_prices"]), 0)

    def test_classify_extreme_price(self):
        """极端高价应被检测"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 600.0, 600.0, 600.0, 600.0, 1000000, 1.0],
        ])
        issues = classify_data_issues(df)
        self.assertGreater(len(issues["extreme_prices"]), 0)

    def test_classify_zero_volume(self):
        """零成交量应被检测"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 0, 1.0],
        ])
        issues = classify_data_issues(df)
        self.assertGreater(len(issues["invalid_records"]), 0)


class TestCorrectBatchAnomalies(unittest.TestCase):
    """测试批量异常修正"""

    def test_correct_extreme_prices(self):
        """修正批量异常中的极端价格"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 2000.0, 2000.0, 2000.0, 2000.0, 1000000, 1.0],
        ])
        events = [{"date": "2024-01-02", "code": "SH600000", "ratio": 0.005}]
        corrected = correct_batch_anomalies(df, events)
        # 极端价格应被设为 NaN
        self.assertTrue(pd.isna(corrected.loc[("2024-01-02", "SH600000"), "$close"]))

    def test_no_events(self):
        """无事件时应返回原始数据副本"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
        ])
        corrected = correct_batch_anomalies(df, [])
        pd.testing.assert_frame_equal(corrected, df)


class TestCorrectSingleStockAnomalies(unittest.TestCase):
    """测试单只股票异常修正"""

    def test_high_median_price(self):
        """中位价>5000的股票应被修正"""
        rows = []
        # 前10行异常高价（模拟未调整的历史价格），后5行正常价格
        # 这样median>5000且第11天出现暴跌(ratio<0.5)触发修正
        for d in range(1, 11):
            rows.append([f"2024-01-{d:02d}", "SH600000", 6000.0, 6000.0, 6000.0, 6000.0, 1000000, 1.0])
        for d in range(11, 16):
            rows.append([f"2024-01-{d:02d}", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0])
        df = _make_price_df(rows)
        corrected = correct_single_stock_anomalies(df)
        # 异常后的价格应被设为 NaN
        self.assertTrue(any(pd.isna(corrected.loc[:, "$close"])))

    def test_normal_stock_not_modified(self):
        """正常股票不应被修改"""
        df = _make_price_df([
            ["2024-01-0" + str(d), "SH600000", 10.0 + d*0.1, 10.0 + d*0.1, 10.1, 9.9, 1000000, 1.0]
            for d in range(1, 6)
        ])
        corrected = correct_single_stock_anomalies(df)
        pd.testing.assert_frame_equal(corrected, df)


class TestApplyTradingRuleCorrections(unittest.TestCase):
    """测试交易规则修正"""

    def test_negative_price_to_nan(self):
        """负价格应被设为 NaN"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", -1.0, -2.0, -3.0, -4.0, 1000000, 1.0],
        ])
        corrected = apply_trading_rule_corrections(df)
        self.assertTrue(pd.isna(corrected.loc[("2024-01-01", "SH600000"), "$open"]))
        self.assertTrue(pd.isna(corrected.loc[("2024-01-01", "SH600000"), "$close"]))

    def test_limit_up_correction(self):
        """涨停价修正：收盘价不应超过涨停价"""
        # 主板前收10元，涨停价11元
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 12.0, 12.0, 12.0, 12.0, 1000000, 1.0],  # 超过涨停
        ])
        corrected = apply_trading_rule_corrections(df)
        # close 应被裁剪到涨停价 11.0
        self.assertLessEqual(corrected.loc[("2024-01-02", "SH600000"), "$close"], 11.0)

    def test_limit_down_correction(self):
        """跌停价修正：收盘价不应低于跌停价"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 8.0, 8.0, 8.0, 8.0, 1000000, 1.0],  # 低于跌停9元
        ])
        corrected = apply_trading_rule_corrections(df)
        self.assertGreaterEqual(corrected.loc[("2024-01-02", "SH600000"), "$close"], 9.0)

    def test_volume_winsorize(self):
        """成交量 winsorize 不应报错（int64→float 转换）"""
        rows = [[f"2024-01-{d:02d}", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0]
                for d in range(1, 21)]
        df = _make_price_df(rows)
        # 最后一行成交量极大
        df.loc[("2024-01-20", "SH600000"), "$volume"] = 100000000
        corrected = apply_trading_rule_corrections(df)
        # 不应报错，且最大值被限制
        self.assertLess(corrected["$volume"].max(), 100000000)


class TestCorrectData(unittest.TestCase):
    """测试全面数据矫正"""

    def test_correct_data_returns_tuple(self):
        """correct_data 应返回 (df, report) 元组"""
        df = _make_price_df([
            ["2024-01-0" + str(d), "SH600000", 10.0, 10.0 + d*0.01, 10.1, 9.9, 1000000, 1.0]
            for d in range(1, 6)
        ])
        corrected, report = correct_data(df, apply_all=False)
        self.assertIsInstance(corrected, pd.DataFrame)
        self.assertIsInstance(report, dict)
        self.assertIn("original_shape", report)
        self.assertIn("corrections", report)

    def test_correct_data_with_anomalies(self):
        """含异常的数据矫正"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", -1.0, -2.0, -3.0, -4.0, 0, 1.0],  # 负价格+零成交量
        ])
        corrected, report = correct_data(df, apply_all=True)
        # 负价格应变为 NaN
        self.assertTrue(pd.isna(corrected.loc[("2024-01-02", "SH600000"), "$close"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
