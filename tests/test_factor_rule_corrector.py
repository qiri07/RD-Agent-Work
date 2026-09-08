#!/usr/bin/env python3
"""
factor_rule_corrector.py 单元测试
==================================
测试因子计算规则矫正：涨跌停标记、价格修正、可交易日过滤。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from unittest import mock

from factor_rule_corrector import (
    add_limit_status, correct_price_anomalies, filter_tradeable_dates,
    detect_lookahead_bias, validate_factor_calculation,
)
from trading_rules import Board


def _make_price_df(rows):
    """创建测试用价格 DataFrame (MultiIndex: datetime, instrument)"""
    data = pd.DataFrame(rows, columns=["date", "instrument", "$open", "$close", "$high", "$low", "$volume", "$factor"])
    data["date"] = pd.to_datetime(data["date"], format="mixed")
    df = data.set_index(["date", "instrument"]).sort_index()
    for c in ["$open", "$close", "$high", "$low", "$volume", "$factor"]:
        if c not in df.columns:
            df[c] = 1.0 if c == "$factor" else 0.0
    return df[["$open", "$close", "$high", "$low", "$volume", "$factor"]]


class TestAddLimitStatus(unittest.TestCase):
    """测试涨跌停状态标记"""

    def test_add_limit_status_basic(self):
        """基础测试：涨停和跌停标记"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 11.0, 11.0, 11.0, 11.0, 1000000, 1.0],  # 涨停
            ["2024-01-03", "SH600000", 9.0, 9.0, 9.0, 9.0, 1000000, 1.0],     # 跌停
        ])
        result = add_limit_status(df)
        self.assertIn("is_limit_up", result.columns)
        self.assertIn("is_limit_down", result.columns)
        # 第2天应标记为涨停
        self.assertTrue(result.loc[("2024-01-02", "SH600000"), "is_limit_up"])
        # 第3天应标记为跌停
        self.assertTrue(result.loc[("2024-01-03", "SH600000"), "is_limit_down"])
        # 第1天不应标记
        self.assertFalse(result.loc[("2024-01-01", "SH600000"), "is_limit_up"])

    def test_add_limit_status_gem(self):
        """创业板涨跌幅20%"""
        df = _make_price_df([
            ["2024-01-01", "SZ300001", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SZ300001", 12.0, 12.0, 12.0, 12.0, 1000000, 1.0],  # 涨停(+20%)
        ])
        result = add_limit_status(df)
        self.assertTrue(result.loc[("2024-01-02", "SZ300001"), "is_limit_up"])

    def test_add_limit_status_bj(self):
        """北交所涨跌幅30%"""
        df = _make_price_df([
            ["2024-01-01", "BJ920000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "BJ920000", 13.0, 13.0, 13.0, 13.0, 1000000, 1.0],  # 涨停(+30%)
        ])
        result = add_limit_status(df)
        self.assertTrue(result.loc[("2024-01-02", "BJ920000"), "is_limit_up"])

    def test_add_limit_status_columns(self):
        """应添加正确的列"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
        ])
        result = add_limit_status(df)
        self.assertIn("board", result.columns)
        self.assertIn("limit_up_price", result.columns)
        self.assertIn("limit_down_price", result.columns)
        self.assertEqual(result.loc[("2024-01-01", "SH600000"), "board"], Board.SH_MAIN)


class TestCorrectPriceAnomalies(unittest.TestCase):
    """测试价格异常修正"""

    def test_negative_price_to_nan(self):
        """负价格应被设为 NaN"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", -1.0, -2.0, -3.0, -4.0, 1000000, 1.0],
        ])
        corrected = correct_price_anomalies(df)
        self.assertTrue(pd.isna(corrected.loc[("2024-01-01", "SH600000"), "$open"]))
        self.assertTrue(pd.isna(corrected.loc[("2024-01-01", "SH600000"), "$close"]))
        self.assertTrue(pd.isna(corrected.loc[("2024-01-01", "SH600000"), "$high"]))
        self.assertTrue(pd.isna(corrected.loc[("2024-01-01", "SH600000"), "$low"]))

    def test_extreme_price_clip(self):
        """>10000的价格应被截断"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 15000.0, 15000.0, 15000.0, 15000.0, 1000000, 1.0],
        ])
        corrected = correct_price_anomalies(df)
        self.assertLessEqual(corrected.loc[("2024-01-01", "SH600000"), "$close"], 10000.0)

    def test_volume_winsorize(self):
        """成交量 winsorize 不应报错"""
        rows = [[f"2024-01-{d:02d}", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0]
                for d in range(1, 21)]
        df = _make_price_df(rows)
        # 最后一行成交量异常大
        df.loc[("2024-01-20", "SH600000"), "$volume"] = 100000000
        corrected = correct_price_anomalies(df)
        # 最大值应被限制
        self.assertLess(corrected["$volume"].max(), 100000000)

    def test_normal_data_unchanged(self):
        """正常数据不应被修改（价格列保持不变）"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.5, 10.6, 10.3, 1000000.0, 1.0],
        ])
        corrected = correct_price_anomalies(df)
        # 价格值应不变（volume dtype可能被转为float）
        self.assertAlmostEqual(corrected.loc[("2024-01-01", "SH600000"), "$close"], 10.5)
        self.assertAlmostEqual(corrected.loc[("2024-01-01", "SH600000"), "$open"], 10.0)


class TestFilterTradeableDates(unittest.TestCase):
    """测试可交易日过滤"""

    def test_filter_zero_volume(self):
        """零成交量应被过滤"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 10.0, 10.0, 10.0, 10.0, 0, 1.0],
            ["2024-01-03", "SH600000", 10.0, 10.0, 10.0, 10.0, 500000, 1.0],
        ])
        result = filter_tradeable_dates(df)
        self.assertEqual(len(result), 2)
        idx = result.index
        self.assertNotIn(("2024-01-02", "SH600000"), idx)

    def test_filter_nan_open(self):
        """NaN开盘价应被过滤"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", np.nan, 10.0, 10.0, 10.0, 1000000, 1.0],
        ])
        result = filter_tradeable_dates(df)
        self.assertEqual(len(result), 1)

    def test_filter_nan_close(self):
        """NaN收盘价应被过滤"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
            ["2024-01-02", "SH600000", 10.0, np.nan, 10.0, 10.0, 1000000, 1.0],
        ])
        result = filter_tradeable_dates(df)
        self.assertEqual(len(result), 1)

    def test_min_volume_threshold(self):
        """低于 min_volume 应被过滤"""
        df = _make_price_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 50, 1.0],  # 成交量太低
            ["2024-01-02", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0],
        ])
        result = filter_tradeable_dates(df, min_volume=100)
        self.assertEqual(len(result), 1)


class TestDetectLookaheadBias(unittest.TestCase):
    """测试未来函数检测"""

    def test_no_bias_normal_factor(self):
        """正常因子不应触发 bias"""
        factor_df = pd.DataFrame({
            "factor_val": [1.0, 1.1, 1.2, 1.15, 1.3]
        }, index=pd.MultiIndex.from_tuples([
            ("2024-01-01", "SH600000"), ("2024-01-02", "SH600000"),
            ("2024-01-03", "SH600000"), ("2024-01-04", "SH600000"),
            ("2024-01-05", "SH600000"),
        ], names=["datetime", "instrument"]))
        prices_df = _make_price_df([
            ["2024-01-0" + str(d), "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0]
            for d in range(1, 6)
        ])
        issues = detect_lookahead_bias(factor_df, prices_df)
        self.assertEqual(len(issues), 0)

    def test_bias_large_changes(self):
        """大幅变化应触发 bias"""
        factor_df = pd.DataFrame({
            "factor_val": [1.0, 100.0, 1.0, 100.0, 1.0]
        }, index=pd.MultiIndex.from_tuples([
            ("2024-01-0" + str(d), "SH600000") for d in range(1, 6)
        ], names=["datetime", "instrument"]))
        prices_df = _make_price_df([
            ["2024-01-0" + str(d), "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0]
            for d in range(1, 6)
        ])
        issues = detect_lookahead_bias(factor_df, prices_df)
        self.assertIn("factor_val", issues)
        self.assertGreater(issues["factor_val"]["large_changes"], 0)


class TestValidateFactorCalculation(unittest.TestCase):
    """测试因子计算验证"""

    def test_validate_normal_factor(self):
        """正常因子验证"""
        dates = pd.date_range("2024-01-01", periods=5)
        idx = pd.MultiIndex.from_product([dates, ["SH600000"]], names=["datetime", "instrument"])
        factor_df = pd.DataFrame({"factor_val": [1.0, 1.1, 1.2, 1.15, 1.3]}, index=idx)
        prices_df = _make_price_df([
            ["2024-01-0" + str(d), "SH600000", 10.0, 10.0 + d*0.1, 10.1, 9.9, 1000000, 1.0]
            for d in range(1, 6)
        ])
        report = validate_factor_calculation(factor_df, prices_df, factor_name="test_factor")
        self.assertEqual(report["factor_name"], "test_factor")
        self.assertEqual(report["stocks"], 1)
        self.assertIn("issues", report)

    def test_validate_shape(self):
        """验证报告包含形状信息"""
        dates = pd.date_range("2024-01-01", periods=3)
        idx = pd.MultiIndex.from_product([dates, ["SH600000"]], names=["datetime", "instrument"])
        factor_df = pd.DataFrame({"f": [1.0, 2.0, 3.0]}, index=idx)
        prices_df = _make_price_df([
            ["2024-01-0" + str(d), "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000, 1.0]
            for d in range(1, 4)
        ])
        report = validate_factor_calculation(factor_df, prices_df)
        self.assertEqual(report["shape"], (3, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
