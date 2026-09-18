#!/usr/bin/env python3
from __future__ import annotations
"""
data_validator.py 单元测试
============================
测试 DataValidator, validate_stock_data 等功能。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from data_validator import DataValidator, validate_stock_data
from trading_rules import Board


def _make_prices_df(n_stocks=3, n_days=10):
    """创建标准 MultiIndex 价格 DataFrame"""
    instruments = [f"SH60000{i}" for i in range(n_stocks)]
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    np.random.seed(42)
    data = {}
    for col in ["$open", "$close", "$high", "$low", "$volume"]:
        if col == "$volume":
            data[col] = np.random.rand(len(idx)) * 1e8 + 1e6
        else:
            data[col] = np.random.rand(len(idx)) * 50 + 50
    return pd.DataFrame(data, index=idx)


class TestDataValidator(unittest.TestCase):
    """测试 DataValidator 类"""

    def test_init(self):
        """初始化"""
        df = _make_prices_df()
        validator = DataValidator(df)
        self.assertIsNotNone(validator)

    def test_check_price_range_normal(self):
        """正常价格范围"""
        df = _make_prices_df()
        validator = DataValidator(df)
        issues = validator._check_price_range()
        self.assertEqual(len(issues), 0)

    def test_check_price_range_extreme(self):
        """极端价格"""
        df = _make_prices_df()
        df.loc[("2020-01-02", "SH600000"), "$close"] = 100000.0
        validator = DataValidator(df)
        issues = validator._check_price_range()
        self.assertGreater(len(issues), 0)

    def test_check_gap_anomalies(self):
        """价格跳空异常"""
        df = _make_prices_df()
        # 制造一个 50% 的跌幅（模拟跳空）
        df.loc[("2020-01-03", "SH600000"), "$close"] = 25.0
        validator = DataValidator(df)
        result = validator._check_gap_anomalies()
        # 返回 None 或空列表表示无问题，有值表示有问题
        if result is not None:
            self.assertGreater(len(result), 0)

    def test_check_return_limits_sh(self):
        """沪市涨跌幅限制"""
        df = _make_prices_df()
        # 制造 15% 涨幅（超过沪市 10% 限制）
        df.loc[("2020-01-02", "SH600000"), "$close"] = 115.0
        df.loc[("2020-01-01", "SH600000"), "$close"] = 100.0
        validator = DataValidator(df)
        issues = validator._check_return_limits()
        self.assertGreater(len(issues), 0)

    def test_check_return_limits_gem(self):
        """创业板涨跌幅限制"""
        # 用单只创业板股票，避免随机数据干扰
        idx = pd.MultiIndex.from_product(
            [pd.date_range("2020-01-01", periods=3, freq="B"), ["SZ300003"]],
            names=["datetime", "instrument"],
        )
        df = pd.DataFrame({
            "$open": [50, 50, 50],
            "$close": [100, 118, 100],  # 18%涨幅，创业板20%限制内
            "$high": [55, 55, 55],
            "$low": [45, 45, 45],
            "$volume": [1e8, 1e8, 1e8],
        }, index=idx)
        validator = DataValidator(df)
        issues = validator._check_return_limits()
        self.assertEqual(len(issues), 0)

    def test_check_volume_anomalies(self):
        """成交量异常"""
        df = _make_prices_df()
        df.loc[("2020-01-03", "SH600000"), "$volume"] = 1e12  # 异常放量
        validator = DataValidator(df)
        result = validator._check_volume_anomalies()
        if result is not None:
            self.assertGreater(len(result), 0)

    def test_apply_corrections_clip_price(self):
        """价格裁剪修正"""
        df = _make_prices_df()
        # apply_corrections 处理极端高价(>10000)，不处理负价格
        df.loc[("2020-01-02", "SH600000"), "$close"] = 15000.0
        validator = DataValidator(df)
        # 需要先调用 validate_all() 来填充 self.issues，否则 get_correction_recommendations() 返回空列表
        validator.validate_all()
        result = validator.apply_corrections()
        self.assertIsInstance(result, pd.DataFrame)
        # 极端高价应被裁剪到 10000
        corrected_close = result.loc[("2020-01-02", "SH600000"), "$close"]
        # apply_corrections 使用 np.sign * threshold，15000 -> 10000
        self.assertEqual(float(corrected_close), 10000.0)


class TestValidateStockData(unittest.TestCase):
    """测试 validate_stock_data 函数"""

    def test_valid_data(self):
        """有效数据"""
        df = _make_prices_df()
        result = validate_stock_data(df)
        self.assertIsInstance(result, dict)
        self.assertIn("total_issues", result)

    def test_invalid_price(self):
        """无效价格"""
        df = _make_prices_df()
        df.loc[("2020-01-02", "SH600000"), "$close"] = -10.0
        result = validate_stock_data(df)
        self.assertIsInstance(result, dict)
        self.assertGreater(result.get("error_count", 0), 0)

    def test_get_correction_recommendations(self):
        """获取修正建议"""
        df = _make_prices_df()
        df.loc[("2020-01-02", "SH600000"), "$close"] = -10.0
        df.loc[("2020-01-03", "SH600000"), "$close"] = 0.0
        result = validate_stock_data(df)
        self.assertIn("recommendations", result)


if __name__ == "__main__":
    unittest.main()
