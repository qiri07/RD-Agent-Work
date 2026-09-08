#!/usr/bin/env python3
"""
data_validator.py 单元测试
===========================
测试 DataValidator 类：价格异常、涨跌幅违规、成交量异常、跳空、ST检测、拆分事件、修正建议。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from data_validator import DataValidator, validate_stock_data, print_trading_rules_summary


def _make_prices_df(rows):
    """创建测试用价格 DataFrame (MultiIndex: datetime, instrument)"""
    data = pd.DataFrame(rows, columns=["date", "instrument", "$open", "$close", "$high", "$low", "$volume"])
    data["date"] = pd.to_datetime(data["date"], format="mixed")
    df = data.set_index(["date", "instrument"]).sort_index()
    for c in ["$open", "$close", "$high", "$low", "$volume"]:
        if c not in df.columns:
            df[c] = 10.0
    return df[["$open", "$close", "$high", "$low", "$volume"]]


class TestDataValidatorInit(unittest.TestCase):
    """测试初始化"""

    def test_init_copies_dataframe(self):
        """应复制而非引用原 DataFrame"""
        df = _make_prices_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],
        ])
        v = DataValidator(df)
        self.assertEqual(len(v.prices), 1)
        # 修改原 DataFrame 不应影响 validator
        df.loc[("2024-01-01", "SH600000"), "$close"] = 999.0
        self.assertAlmostEqual(v.prices.loc[("2024-01-01", "SH600000"), "$close"], 10.0)


class TestCheckPriceRange(unittest.TestCase):
    """测试价格范围检测"""

    def test_normal_prices_no_issue(self):
        """正常价格不应报告问题"""
        df = _make_prices_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],
            ["2024-01-02", "SH600000", 10.5, 10.5, 10.6, 10.4, 1100000],
        ])
        v = DataValidator(df)
        v._check_price_range()
        self.assertNotIn("price_extreme", v.issues)

    def test_extreme_price_detected(self):
        """价格>10000 应被检测"""
        df = _make_prices_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],
            ["2024-01-02", "SH600000", 15000.0, 15000.0, 15000.0, 15000.0, 1000000],
        ])
        v = DataValidator(df)
        v._check_price_range()
        # 实际 key 格式为 $close_extreme, $open_extreme 等（每列单独统计）
        extreme_keys = [k for k in v.issues if 'extreme' in k]
        self.assertGreater(len(extreme_keys), 0)
        self.assertEqual(v.issues['$close_extreme']["count"], 1)  # 仅1行数据超标

    def test_negative_price_not_flagged_by_range(self):
        """负价格在 _check_price_range 中不被视为 extreme（那是 corrector 的职责）"""
        df = _make_prices_df([
            ["2024-01-01", "SH600000", -5.0, -5.0, -5.0, -5.0, 1000000],
        ])
        v = DataValidator(df)
        v._check_price_range()
        # 负价格不触发 extreme 检测（>10000 阈值）
        self.assertNotIn("price_extreme", v.issues)


class TestCheckReturnLimits(unittest.TestCase):
    """测试涨跌幅违规检测"""

    def test_sh_main_limit(self):
        """主板股票涨跌停±10% 应正确检测"""
        df = _make_prices_df([
            ["2024-01-02", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],  # 前收
            ["2024-01-03", "SH600000", 12.0, 12.0, 12.0, 12.0, 1000000],  # +20%，超涨停
        ])
        v = DataValidator(df)
        v._check_return_limits()
        self.assertIn("沪主板_return_violation", v.issues)

    def test_gem_limit(self):
        """科创板/创业板涨跌停±20%"""
        df = _make_prices_df([
            ["2024-01-02", "SH688001", 10.0, 10.0, 10.0, 10.0, 1000000],
            ["2024-01-03", "SH688001", 13.0, 13.0, 13.0, 13.0, 1000000],  # +30%，超科创板涨停
        ])
        v = DataValidator(df)
        v._check_return_limits()
        self.assertIn("科创板_return_violation", v.issues)

    def test_normal_data_no_violation(self):
        """正常数据不应报告违规"""
        df = _make_prices_df([
            ["2024-01-02", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],
            ["2024-01-03", "SH600000", 10.5, 10.5, 10.6, 10.4, 1000000],  # +5%
        ])
        v = DataValidator(df)
        v._check_return_limits()
        violations = {k for k in v.issues if "return_violation" in k}
        self.assertEqual(len(violations), 0)


class TestCheckVolumeAnomalies(unittest.TestCase):
    """测试成交量异常检测"""

    def test_normal_volume_no_anomaly(self):
        """正常成交量不应报告异常"""
        rows = [["2024-01-{:02d}".format(d), "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000]
                for d in range(1, 21)]
        df = _make_prices_df(rows)
        v = DataValidator(df)
        v._check_volume_anomalies()
        self.assertNotIn("volume_anomaly", v.issues)

    def test_sudden_volume_spike_detected(self):
        """成交量突增应被检测"""
        rows = [["2024-01-{:02d}".format(d), "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000]
                for d in range(1, 20)]
        rows.append(["2024-01-20", "SH600000", 10.0, 10.0, 10.0, 10.0, 50000000])  # 50倍
        df = _make_prices_df(rows)
        v = DataValidator(df)
        v._check_volume_anomalies()
        self.assertIn("volume_anomaly", v.issues)


class TestCheckGapAnomalies(unittest.TestCase):
    """测试开盘跳空检测"""

    def test_normal_open_no_gap(self):
        """正常开盘跳空不应报告"""
        df = _make_prices_df([
            ["2024-01-02", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],
            ["2024-01-03", "SH600000", 10.1, 10.5, 10.6, 10.4, 1000000],  # 跳空1%
        ])
        v = DataValidator(df)
        v._check_gap_anomalies()
        self.assertNotIn("open_gap", v.issues)

    def test_large_gap_detected(self):
        """开盘跳空>10% 应被检测"""
        df = _make_prices_df([
            ["2024-01-02", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],
            ["2024-01-03", "SH600000", 12.0, 12.0, 12.0, 12.0, 1000000],  # +20% 跳空
        ])
        v = DataValidator(df)
        v._check_gap_anomalies()
        self.assertIn("open_gap", v.issues)


class TestCheckSTStatus(unittest.TestCase):
    """测试ST股嫌疑检测"""

    def test_normal_stock_not_st_suspect(self):
        """正常波动不应被识别为ST嫌疑"""
        rows = [["2024-01-{:02d}".format(d), "SH600000", 10.0, 10.0 + d * 0.01, 10.1, 9.9, 1000000]
                for d in range(1, 28)]  # 只用27天（1月最多31天，避开非法日期）
        df = _make_prices_df(rows)
        v = DataValidator(df)
        v._check_st_status()
        self.assertNotIn("st_suspects", v.issues)


class TestCheckSplitEvents(unittest.TestCase):
    """测试拆分事件检测"""

    def test_no_split_normal_data(self):
        """正常数据不应检测到拆分"""
        df = _make_prices_df([
            ["2024-01-02", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],
            ["2024-01-03", "SH600000", 10.5, 10.5, 10.6, 10.4, 1000000],
        ])
        v = DataValidator(df)
        v._check_split_events()
        self.assertNotIn("split_events", v.issues)

    def test_large_drop_detected_as_split(self):
        """价格暴跌应被检测为疑似拆分"""
        df = _make_prices_df([
            ["2024-01-02", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],
            ["2024-01-03", "SH600000", 3.0, 3.0, 3.0, 3.0, 5000000],  # -70%
        ])
        v = DataValidator(df)
        v._check_split_events()
        self.assertIn("split_events", v.issues)


class TestGetCorrectionRecommendations(unittest.TestCase):
    """测试修正建议生成"""

    def test_extreme_price_recommendation(self):
        """价格极端问题应给出截断建议"""
        df = _make_prices_df([
            ["2024-01-01", "SH600000", 15000.0, 15000.0, 15000.0, 15000.0, 1000000],
        ])
        v = DataValidator(df)
        v.validate_all()
        recs = v.get_correction_recommendations()
        actions = [r["action"] for r in recs]
        self.assertIn("clip_extreme_prices", actions)

    def test_volume_recommendation(self):
        """成交量异常应给出截断建议"""
        rows = [["2024-01-{:02d}".format(d), "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000]
                for d in range(1, 20)]
        rows.append(["2024-01-20", "SH600000", 10.0, 10.0, 10.0, 10.0, 50000000])
        df = _make_prices_df(rows)
        v = DataValidator(df)
        v.validate_all()
        recs = v.get_correction_recommendations()
        actions = [r["action"] for r in recs]
        self.assertIn("clip_volume", actions)

    def test_clean_data_no_recommendations(self):
        """干净数据不应有修正建议"""
        df = _make_prices_df([
            ["2024-01-{:02d}".format(d), "SH600000", 10.0, 10.0 + d * 0.01, 10.1, 9.9, 1000000]
            for d in range(1, 11)
        ])
        v = DataValidator(df)
        v.validate_all()
        recs = v.get_correction_recommendations()
        self.assertEqual(len(recs), 0)


class TestApplyCorrections(unittest.TestCase):
    """测试数据修正应用"""

    def test_clip_extreme_prices(self):
        """极端价格应被截断"""
        df = _make_prices_df([
            ["2024-01-01", "SH600000", 15000.0, 15000.0, 15000.0, 15000.0, 1000000],
        ])
        v = DataValidator(df)
        v.validate_all()
        corrected = v.apply_corrections()
        self.assertLessEqual(corrected.loc[("2024-01-01", "SH600000"), "$close"], 10000.0)

    def test_clip_volume(self):
        """异常成交量应被截断（修复 int64 LossySetitemError）"""
        rows = [["2024-01-{:02d}".format(d), "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000]
                for d in range(1, 20)]
        rows.append(["2024-01-20", "SH600000", 10.0, 10.0, 10.0, 10.0, 50000000])
        df = _make_prices_df(rows)
        v = DataValidator(df)
        v.validate_all()
        corrected = v.apply_corrections()
        # 20日成交量应被限制（不再抛出 LossySetitemError）
        vol_20 = corrected.loc[("2024-01-20", "SH600000"), "$volume"]
        self.assertLess(vol_20, 50000000)


class TestValidateStockData(unittest.TestCase):
    """测试 validate_stock_data 函数"""

    def test_returns_dict_with_issues(self):
        """应返回包含问题统计的字典"""
        df = _make_prices_df([
            ["2024-01-01", "SH600000", 10.0, 10.0, 10.0, 10.0, 1000000],
        ])
        result = validate_stock_data(df)
        self.assertIsInstance(result, dict)
        self.assertIn("total_issues", result)
        self.assertIn("error_count", result)
        self.assertIn("warning_count", result)


class TestPrintTradingRulesSummary(unittest.TestCase):
    """测试 print_trading_rules_summary（只验证不报错）"""

    def test_prints_no_error(self):
        """应正常打印不出错"""
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            print_trading_rules_summary()
        output = f.getvalue()
        self.assertGreater(len(output), 0)
        self.assertIn("交易规则", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
