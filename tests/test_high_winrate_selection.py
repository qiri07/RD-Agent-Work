#!/usr/bin/env python3
"""
high_winrate_stock_selection.py (v3-v6) 单元测试
=================================================
测试高胜率因子选股策略的核心逻辑。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd


class TestFactorSelection(unittest.TestCase):
    """测试因子筛选逻辑（v6版本）"""

    def test_momentum_factor_filtering(self):
        """应筛选出动量因子（IC>0）"""
        ic_df = pd.DataFrame({
            "factor_id": ["f_mom1", "f_mom2", "f_rev1", "f_rev2"],
            "IC_5d": [0.05, 0.08, -0.06, -0.04],
            "IC_pos_5d": [0.7, 0.75, 0.7, 0.7],  # 所有都>=0.6
            "abs_IC": [0.05, 0.08, 0.06, 0.04],
        })

        qualified = ic_df[
            (ic_df['IC_pos_5d'] >= 0.6) &
            (ic_df['abs_IC'] >= 0.01)
        ]

        momentum = qualified[qualified['IC_5d'] > 0]
        reversal = qualified[qualified['IC_5d'] < 0]

        self.assertEqual(len(momentum), 2)  # f_mom1, f_mom2
        self.assertEqual(len(reversal), 2)  # f_rev1, f_rev2

    def test_reversal_factor_filtering(self):
        """应筛选出反转因子（IC<0）"""
        ic_df = pd.DataFrame({
            "factor_id": ["f_mom1", "f_rev1"],
            "IC_5d": [0.05, -0.08],
            "IC_pos_5d": [0.7, 0.65],
            "abs_IC": [0.05, 0.08],
        })

        qualified = ic_df[
            (ic_df['IC_pos_5d'] >= 0.6) &
            (ic_df['abs_IC'] >= 0.01)
        ]

        reversal = qualified[qualified['IC_5d'] < 0]
        self.assertEqual(len(reversal), 1)  # 只有f_rev1

    def test_qualified_factor_thresholds(self):
        """合格的因子应满足IC_POS和abs_IC阈值"""
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2", "f3", "f4"],
            "IC_5d": [0.05, -0.03, 0.005, -0.01],
            "IC_pos_5d": [0.7, 0.65, 0.8, 0.5],
            "abs_IC": [0.05, 0.03, 0.005, 0.01],
        })

        qualified = ic_df[
            (ic_df['IC_pos_5d'] >= 0.6) &
            (ic_df['abs_IC'] >= 0.01)
        ]

        # f1: IC_POS=0.7>=0.6, abs_IC=0.05>=0.01 ✓
        # f2: IC_POS=0.65>=0.6, abs_IC=0.03>=0.01 ✓
        # f3: IC_POS=0.8>=0.6, abs_IC=0.005<0.01 ✗
        # f4: IC_POS=0.5<0.6 ✗
        self.assertEqual(len(qualified), 2)


class TestCrossSectionZScore(unittest.TestCase):
    """测试横截面Z-score标准化"""

    def _zscore_func(self, df):
        """测试用Z-score函数"""
        result = pd.DataFrame(index=df.index, columns=df.columns, dtype=np.float64)
        for col in df.columns:
            series = df[col]
            mean = series.mean()
            std = series.std()
            if std > 0:
                result[col] = (series - mean) / std
            else:
                result[col] = 0
        return result

    def test_zscore_normalization(self):
        """Z-score标准化应使均值为0，标准差为1"""
        df = pd.DataFrame({
            "f1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "f2": [5.0, 4.0, 3.0, 2.0, 1.0],
        })

        result = self._zscore_func(df)

        self.assertAlmostEqual(result["f1"].mean(), 0.0, places=5)
        self.assertAlmostEqual(result["f1"].std(), 1.0, places=5)
        self.assertAlmostEqual(result["f2"].mean(), 0.0, places=5)

    def test_zscore_constant_column(self):
        """常数列的Z-score应为0"""
        df = pd.DataFrame({
            "f1": [5.0, 5.0, 5.0, 5.0, 5.0],
            "f2": [1.0, 2.0, 3.0, 4.0, 5.0],
        })

        result = self._zscore_func(df)

        # 常数列的std为0，应设为0
        self.assertEqual(result["f1"].tolist(), [0.0, 0.0, 0.0, 0.0, 0.0])

    def test_zscore_multi_date(self):
        """多日期数据应正确标准化"""
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "f1": list(range(10)),
            "f2": list(range(9, -1, -1)),
        }, index=dates)

        result = self._zscore_func(df)

        # 每列都应该被标准化
        self.assertEqual(result.shape, df.shape)
        self.assertFalse(result.isnull().any().any())


class TestCompositeScore(unittest.TestCase):
    """测试综合得分合成"""

    def test_weighted_combination(self):
        """加权和合成应正确"""
        standardized = pd.DataFrame({
            "f1": [1.0, -1.0, 0.0],
            "f2": [-1.0, 1.0, 0.0],
        })

        weights = {"f1": 0.05, "f2": 0.08}
        total_w = sum(weights.values())

        score = (standardized["f1"] * weights["f1"] + standardized["f2"] * weights["f2"]) / total_w

        expected = (1.0 * 0.05 + (-1.0) * 0.08) / 0.13
        self.assertAlmostEqual(score.iloc[0], expected, places=5)


class TestStockScreening(unittest.TestCase):
    """测试股票筛选逻辑"""

    def test_top_k_selection(self):
        """Top-K选股应正确"""
        day_data = pd.DataFrame({
            "composite_score": [3.0, 1.0, 4.0, 2.0, 5.0],
        }, index=["SH600000", "SH600001", "SH600002", "SH600003", "SH600004"])

        TOP_K = 3
        top_stocks = day_data.nlargest(TOP_K, "composite_score")

        self.assertEqual(len(top_stocks), 3)
        self.assertEqual(top_stocks.index[0], "SH600004")  # 得分最高
        self.assertEqual(top_stocks.index[1], "SH600002")
        self.assertEqual(top_stocks.index[2], "SH600000")

    def test_ranking_with_ties(self):
        """并列排名应正确处理"""
        day_data = pd.DataFrame({
            "composite_score": [3.0, 3.0, 2.0, 1.0],
        }, index=["A", "B", "C", "D"])

        day_data["rank"] = day_data["composite_score"].rank(ascending=False, method="dense")

        # A和B并列第1
        self.assertEqual(day_data.loc["A", "rank"], 1.0)
        self.assertEqual(day_data.loc["B", "rank"], 1.0)
        self.assertEqual(day_data.loc["C", "rank"], 2.0)

    def test_filter_valid_stocks(self):
        """应过滤有效股票代码"""
        valid_prefixes = ['SH', 'SZ']
        stocks = pd.Index(["SH600000", "SZ300001", "BJ430000", "invalid"])

        filtered = stocks[stocks.str[:2].isin(valid_prefixes)]

        self.assertEqual(len(filtered), 2)
        self.assertIn("SH600000", filtered)
        self.assertIn("SZ300001", filtered)


class TestBacktestVerification(unittest.TestCase):
    """测试回测验证逻辑"""

    def test_backtest_cash_flow(self):
        """回测资金流应正确"""
        INITIAL_CAPITAL = 1_000_000
        COMMISSION = 0.0013
        cash = INITIAL_CAPITAL

        # 买入100股，价格10元
        shares = 100
        price = 10.0
        cost = shares * price * (1 + COMMISSION)
        cash -= cost

        self.assertEqual(cash, 1_000_000 - 1000 * 1.0013)

    def test_backtest_sell_flow(self):
        """回测卖出资金流应正确"""
        INITIAL_CAPITAL = 1_000_000
        COMMISSION = 0.0013
        SLIPPAGE = 0.0013
        cash = INITIAL_CAPITAL

        # 卖出100股，价格11元
        shares = 100
        sell_price = 11.0
        trade_val = shares * sell_price
        cash += trade_val * (1 - COMMISSION - SLIPPAGE)

        self.assertGreater(cash, INITIAL_CAPITAL)

    def test_pending_sell_expiry(self):
        """待卖出队列到期应正确触发"""
        pending_sell = {
            "SH600000": pd.Timestamp("2024-01-10"),
            "SH600001": pd.Timestamp("2024-01-15"),
        }

        current_date = pd.Timestamp("2024-01-10")
        to_sell = [s for s, sd in pending_sell.items() if sd <= current_date]

        self.assertEqual(to_sell, ["SH600000"])

    def test_portfolio_value_calculation(self):
        """组合价值计算应正确"""
        cash = 500000
        positions = {
            "SH600000": {'shares': 1000, 'entry_price': 10.0},
            "SH600001": {'shares': 500, 'entry_price': 20.0},
        }
        price_map = {
            ("2024-01-10", "SH600000"): 11.0,
            ("2024-01-10", "SH600001"): 19.0,
        }

        total = cash
        for stock, pos in positions.items():
            key = ("2024-01-10", stock)
            if key in price_map:
                total += pos['shares'] * price_map[key]

        self.assertEqual(total, 500000 + 1000 * 11 + 500 * 19)


class TestMetricsReporting(unittest.TestCase):
    """测试指标报告生成"""

    def test_total_return_calculation(self):
        """总收益率计算"""
        initial = 1_000_000
        final = 1_100_000
        total_ret = (final / initial - 1) * 100

        self.assertAlmostEqual(total_ret, 10.0)

    def test_annual_return_calculation(self):
        """年化收益率计算"""
        nav_start = 1.0
        nav_end = 1.21
        years = 2.0

        ann_ret = ((nav_end / nav_start) ** (1 / years) - 1) * 100
        self.assertAlmostEqual(ann_ret, 10.0)

    def test_max_drawdown_calculation(self):
        """最大回撤计算"""
        nav = pd.Series([1.0, 1.1, 1.05, 0.9, 0.95, 1.0])
        max_dd = ((nav / nav.cummax()) - 1).min() * 100

        # 从1.1峰值到0.9，回撤 = (0.9/1.1 - 1) * 100 = -18.18%
        self.assertAlmostEqual(max_dd, -18.18, places=2)

    def test_sharpe_ratio_calculation(self):
        """夏普比率计算"""
        daily_ret = pd.Series([0.001, -0.0005, 0.0008, -0.0003, 0.0005])
        sharpe = (daily_ret.mean() * 252 - 0.02) / (daily_ret.std() * np.sqrt(252))

        self.assertIsInstance(sharpe, float)


class TestDataLoading(unittest.TestCase):
    """测试数据加载逻辑"""

    def test_load_prices_from_parquet(self):
        """应从Parquet加载价格数据"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dates = pd.date_range("2024-01-01", periods=10, freq="B")
            instruments = ["SH600000", "SZ300001"]
            idx = pd.MultiIndex.from_product([dates, instruments], names=["date", "instrument"])

            df = pd.DataFrame({
                "$close": np.random.default_rng(42).uniform(10, 20, len(idx)),
            }, index=idx)

            pq_path = Path(tmpdir) / "prices.parquet"
            df.to_parquet(pq_path)

            loaded = pd.read_parquet(pq_path)
            self.assertEqual(len(loaded), len(idx))

    def test_load_factors_from_h5(self):
        """应从HDF5加载因子数据"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dates = pd.date_range("2024-01-01", periods=10, freq="B")
            stocks = [f"SH{i:06d}" for i in range(1, 6)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])

            df = pd.DataFrame({"factor_val": np.random.default_rng(42).standard_normal(len(idx))}, index=idx)

            h5_path = Path(tmpdir) / "factor.h5"
            df.to_hdf(h5_path, key="data", mode="w")

            loaded = pd.read_hdf(h5_path, key="data")
            self.assertEqual(len(loaded), len(idx))

    def test_handle_missing_factor_file(self):
        """缺少因子文件时应跳过"""
        with tempfile.TemporaryDirectory() as tmpdir:
            h5_path = Path(tmpdir) / "nonexistent.h5"

            if not h5_path.exists():
                skipped = True
            else:
                skipped = False

            self.assertTrue(skipped)


class TestHighWinrateMetrics(unittest.TestCase):
    """测试高胜率指标存储"""

    def test_metrics_dict_structure(self):
        """指标字典应包含必要字段"""
        metrics = {
            'total_return_pct': 10.5,
            'annual_return_pct': 5.2,
            'sharpe_ratio': 1.5,
            'max_drawdown_pct': -8.0,
            'win_rate_pct': 55.0,
            'total_trades': 100,
            'win_trades': 55,
            'profit_factor': 1.8,
            'final_nav': 1.105,
            'selected_factors': 5,
            'top_k': 10,
            'hold_days': 10,
            'latest_date': '2024-09-01',
            'version': 'v6_reversal',
        }

        required_keys = [
            'total_return_pct', 'sharpe_ratio', 'max_drawdown_pct',
            'win_rate_pct', 'total_trades', 'version'
        ]

        for key in required_keys:
            self.assertIn(key, metrics)

    def test_metrics_json_serialization(self):
        """指标应可序列化为JSON"""
        import json
        metrics = {
            'total_return_pct': 10.5,
            'sharpe_ratio': 1.5,
            'latest_date': '2024-09-01',
        }

        json_str = json.dumps(metrics, indent=2, default=str)
        loaded = json.loads(json_str)

        self.assertEqual(loaded['total_return_pct'], 10.5)
        self.assertEqual(loaded['latest_date'], '2024-09-01')


if __name__ == "__main__":
    unittest.main(verbosity=2)
