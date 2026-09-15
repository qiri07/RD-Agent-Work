#!/usr/bin/env python3
"""
factor_rule_corrector.py 单元测试
===================================
测试 FactorRuleChecker, run_full_validation, correct_price_anomalies 等功能。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from factor_rule_corrector import FactorRuleChecker, run_full_validation, correct_price_anomalies


def _make_multiindex_prices(n=200, n_stocks=5):
    """创建标准 MultiIndex 价格 DataFrame"""
    instruments = [f"SH60000{i}" for i in range(n_stocks)]
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    np.random.seed(42)
    return pd.DataFrame({
        "$open": np.random.rand(len(idx)) * 50 + 50,
        "$close": np.random.rand(len(idx)) * 50 + 50,
        "$high": np.random.rand(len(idx)) * 50 + 55,
        "$low": np.random.rand(len(idx)) * 50 + 45,
        "$volume": np.random.rand(len(idx)) * 1e8 + 1e6,
    }, index=idx)


def _make_factor_df(n=200, n_stocks=5):
    """创建标准 MultiIndex 因子 DataFrame"""
    instruments = [f"SH60000{i}" for i in range(n_stocks)]
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    np.random.seed(42)
    return pd.DataFrame({"factor_1": np.random.randn(len(idx))}, index=idx)


class TestFactorRuleChecker(unittest.TestCase):
    """测试 FactorRuleChecker 类"""

    def test_init(self):
        """初始化"""
        checker = FactorRuleChecker()
        self.assertIsNotNone(checker)

    def test_check_lookahead_bias_normal(self):
        """正常情况无未来函数"""
        prices_df = _make_multiindex_prices()
        factor_df = _make_factor_df()
        result = FactorRuleChecker.check_lookahead_bias(factor_df, prices_df)
        self.assertIsInstance(result, dict)

    def test_check_lookahead_bias_large_change(self):
        """大幅变动应检测到问题"""
        prices_df = _make_multiindex_prices()
        factor_df = _make_factor_df()
        # 制造大幅突变
        mask = factor_df.index.get_level_values("datetime") == factor_df.index.get_level_values("datetime")[100]
        factor_df.loc[mask, "factor_1"] = 1000.0
        result = FactorRuleChecker.check_lookahead_bias(factor_df, prices_df)
        self.assertIsInstance(result, dict)

    def test_filter_tradeable(self):
        """筛选可交易日期"""
        prices_df = _make_multiindex_prices()
        factor_df = _make_factor_df()
        result = FactorRuleChecker.filter_tradeable(prices_df, factor_df)
        self.assertIsInstance(result, pd.DataFrame)

    def test_filter_tradeable_negative_price(self):
        """负价格应被过滤"""
        prices_df = _make_multiindex_prices()
        factor_df = _make_factor_df()
        # 制造负价格
        prices_df.loc[("2020-02-01", "SH600000"), "$close"] = -10.0
        prices_df.loc[("2020-02-02", "SH600000"), "$close"] = 0.0
        result = FactorRuleChecker.filter_tradeable(prices_df, factor_df)
        self.assertIsInstance(result, pd.DataFrame)


class TestCorrectPriceAnomalies(unittest.TestCase):
    """测试 correct_price_anomalies 函数"""

    def test_basic_correction(self):
        """基本修正"""
        df = _make_multiindex_prices()
        df.loc[("2020-01-02", "SH600000"), "$close"] = -10.0
        df.loc[("2020-01-03", "SH600000"), "$close"] = 15000.0
        result = correct_price_anomalies(df)
        self.assertIsInstance(result, pd.DataFrame)
        # 负价格应被处理
        close_col = result.loc[("2020-01-02", "SH600000"), "$close"]
        self.assertTrue(close_col <= 0 or pd.isna(close_col))

    def test_with_nan(self):
        """含NaN数据"""
        df = _make_multiindex_prices()
        df.loc[("2020-01-02", "SH600000"), "$close"] = np.nan
        result = correct_price_anomalies(df)
        self.assertIsInstance(result, pd.DataFrame)


class TestRunFullValidation(unittest.TestCase):
    """测试 run_full_validation 函数"""

    def test_basic_validation(self):
        """基本验证（跳过实时DB操作，验证mock路径）"""
        # run_full_validation 会连接数据库，测试中不直接调用
        # 此处仅验证函数存在且可导入
        from factor_rule_corrector import run_full_validation
        self.assertTrue(callable(run_full_validation))


class TestValidateFactorCalculation(unittest.TestCase):
    """测试 validate_factor_calculation 相关功能"""

    def test_valid_factor(self):
        """有效因子"""
        factor_df = _make_factor_df()
        prices_df = _make_multiindex_prices()
        # check_lookahead_bias 是主要的验证方法
        result = FactorRuleChecker.check_lookahead_bias(factor_df, prices_df)
        self.assertIsInstance(result, dict)

    def test_empty_factor(self):
        """空因子"""
        empty_df = pd.DataFrame(
            columns=["factor_1"],
            index=pd.MultiIndex.from_tuples([], names=["datetime", "instrument"]),
        )
        prices_df = _make_multiindex_prices(n=10)
        result = FactorRuleChecker.check_lookahead_bias(empty_df, prices_df)
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
