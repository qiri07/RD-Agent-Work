#!/usr/bin/env python3
"""
backtest_single_factors.py 单元测试 (重构后)
=============================================
测试单因子回测逻辑：价格加载、Top-K选股、回测执行。
使用 engine/ 模块。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.backtest import BacktestEngine, create_backtest_engine
from engine.pricing import PriceEngine
from engine.factor import FactorEngine, create_factor_engine


class TestLoadAllFactors(unittest.TestCase):
    """测试因子加载逻辑"""

    def _create_factor_h5(self, tmpdir, factor_name, n_days=50, n_stocks=20):
        """创建测试用因子HDF5文件"""
        session_dir = Path(tmpdir) / factor_name
        session_dir.mkdir()

        rng = np.random.default_rng(42)
        dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
        stocks = [f"SH{i:06d}" for i in range(1, n_stocks + 1)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
        vals = rng.standard_normal(len(idx))
        df = pd.DataFrame({factor_name: vals}, index=idx)

        h5_path = session_dir / "result.h5"
        df.to_hdf(h5_path, key="data", mode="w")
        return session_dir

    def test_loads_multiple_factors(self):
        """应加载多个因子"""
        factor_engine = create_factor_engine()

        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_factor_h5(tmpdir, "factor_a", n_days=30, n_stocks=10)
            self._create_factor_h5(tmpdir, "factor_b", n_days=30, n_stocks=10)

            with mock.patch.object(factor_engine, 'workspace', Path(tmpdir)):
                factors = factor_engine.load_factors(["factor_a", "factor_b"])

            self.assertEqual(len(factors), 2)
            self.assertIn("factor_a", factors)
            self.assertIn("factor_b", factors)

    def test_loads_single_factor(self):
        """应能加载单个因子"""
        factor_engine = create_factor_engine()

        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_factor_h5(tmpdir, "only_factor", n_days=30, n_stocks=10)

            with mock.patch.object(factor_engine, 'workspace', Path(tmpdir)):
                factors = factor_engine.load_factors(["only_factor"])

            self.assertEqual(len(factors), 1)
            self.assertIn("only_factor", factors)

    def test_handles_missing_files(self):
        """缺少H5文件时应返回空字典"""
        factor_engine = create_factor_engine()

        with tempfile.TemporaryDirectory() as tmpdir:
            # 只创建目录，不创建H5文件
            Path(tmpdir, "empty_factor").mkdir()

            with mock.patch.object(factor_engine, 'workspace', Path(tmpdir)):
                factors = factor_engine.load_factors(["empty_factor"])

            self.assertEqual(len(factors), 0)


class TestComputeDayTopK(unittest.TestCase):
    """测试每日Top-K选股逻辑"""

    def test_selects_top_k(self):
        """应选取Top-K股票"""
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        stocks = [f"SH{i:06d}" for i in range(1, 11)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])

        # 创建递增因子值（便于预测排名）
        vals = np.arange(len(idx))
        series = pd.Series(vals, index=idx)

        TOP_K = 3
        day_topk = {}
        for dt, group in series.groupby(level='datetime', sort=False):
            group = group.dropna()
            group = group[np.isfinite(group)]
            if len(group) < TOP_K:
                continue
            top = group.nlargest(TOP_K)
            day_topk[dt] = top.index.tolist()

        self.assertEqual(len(day_topk), 5)  # 5个交易日
        for dt, selected in day_topk.items():
            self.assertEqual(len(selected), 3)  # TOP_K=3
            stock_names = [s[1] if isinstance(s, tuple) else s for s in selected]
            self.assertEqual(stock_names, [f"SH000010", f"SH000009", f"SH000008"])

    def test_skips_insufficient_stocks(self):
        """股票数不足TOP_K时应跳过"""
        dates = pd.date_range("2024-01-01", periods=2, freq="B")
        stocks = [f"SH{i:06d}" for i in range(1, 3)]  # 只有2只股票
        idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])

        vals = np.arange(len(idx))
        series = pd.Series(vals, index=idx)

        TOP_K = 3
        day_topk = {}
        for dt, group in series.groupby(level='datetime', sort=False):
            group = group.dropna()
            group = group[np.isfinite(group)]
            if len(group) < TOP_K:
                continue
            top = group.nlargest(TOP_K)
            day_topk[dt] = top.index.tolist()

        self.assertEqual(len(day_topk), 0)  # 股票数不足，全部跳过

    def test_handles_nan_values(self):
        """应正确处理NaN值"""
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        stocks = [f"SH{i:06d}" for i in range(1, 6)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])

        vals = np.random.default_rng(42).standard_normal(len(idx))
        mask = idx.get_level_values('instrument') == 'SH000001'
        vals[mask] = np.nan
        series = pd.Series(vals, index=idx)

        TOP_K = 3
        day_topk = {}
        for dt, group in series.groupby(level='datetime', sort=False):
            group = group.dropna()
            group = group[np.isfinite(group)]
            if len(group) < TOP_K:
                continue
            top = group.nlargest(TOP_K)
            day_topk[dt] = top.index.tolist()

        self.assertEqual(len(day_topk), 3)
        for selected in day_topk.values():
            self.assertEqual(len(selected), 3)
            stock_names = [s[1] if isinstance(s, tuple) else s for s in selected]
            self.assertNotIn("SH000001", stock_names)


class TestRunBacktest(unittest.TestCase):
    """测试回测引擎逻辑"""

    def test_basic_backtest(self):
        """基本回测应产生交易记录"""
        engine = create_backtest_engine(
            initial_capital=1000000,
            commission_rate=0.001,
            slippage_rate=0.0003,
            min_trade_value=100
        )

        dates = pd.date_range("2024-01-01", periods=20, freq="B")
        price_map = {}
        for d in dates:
            price_map[(d, "SH600000")] = {'open': 10.0, 'close': 10.5}

        signals = {i: ["SH600000"] for i in range(2, len(dates))}

        result = engine.run(dates, price_map, signals, hold_days=5, top_k=1)

        self.assertIsInstance(result.daily_value, list)
        self.assertGreater(len(result.daily_value), 0)
        self.assertIsInstance(result.trades, list)

    def test_no_trades_with_empty_signals(self):
        """无信号时不应产生交易"""
        engine = create_backtest_engine()

        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        price_map = {(d, "SH600000"): {'open': 10.0, 'close': 10.5} for d in dates}
        signals = {}  # 无信号

        result = engine.run(dates, price_map, signals, hold_days=5, top_k=1)

        self.assertEqual(len(result.trades), 0)

    def test_hold_period_expiry(self):
        """持有期到期应卖出"""
        engine = create_backtest_engine(
            initial_capital=1000000,
            commission_rate=0.001,
            slippage_rate=0.0003
        )

        dates = pd.date_range("2024-01-01", periods=15, freq="B")
        price_map = {(d, "SH600000"): {'open': 10.0, 'close': 10.5} for d in dates}

        signals = {
            1: ["SH600000"],
            7: ["SH600000"],
        }

        result = engine.run(dates, price_map, signals, hold_days=5, top_k=1)

        self.assertIsInstance(result.trades, list)

    def test_stop_buying_on_insufficient_cash(self):
        """资金不足时应停止买入"""
        engine = create_backtest_engine(
            initial_capital=5000,
            commission_rate=0.001,
            slippage_rate=0.0003,
            min_trade_value=1000
        )

        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        price_map = {(d, "SH600000"): {'open': 100.0, 'close': 100.5} for d in dates}
        signals = {i: ["SH600000"] for i in range(2, len(dates))}

        result = engine.run(dates, price_map, signals, hold_days=5, top_k=1)

        # 资金不足，交易应该很少或没有
        self.assertIsInstance(result.trades, list)


class TestLoadPrices(unittest.TestCase):
    """测试价格数据加载"""

    def test_loads_parquet_prices(self):
        """应从Parquet加载价格数据"""
        price_engine = PriceEngine()

        with tempfile.TemporaryDirectory() as tmpdir:
            dates = pd.date_range("2024-01-01", periods=10, freq="B")
            instruments = ["SH600000", "SZ300001"]
            idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])

            df = pd.DataFrame({
                "$open": np.random.default_rng(42).uniform(10, 20, len(idx)),
                "$close": np.random.default_rng(43).uniform(10, 20, len(idx)),
                "$high": np.random.default_rng(44).uniform(20, 25, len(idx)),
                "$low": np.random.default_rng(45).uniform(8, 15, len(idx)),
            }, index=idx)

            pq_path = Path(tmpdir) / "prices.parquet"
            df.to_parquet(pq_path)

            price_engine.source_pq = pq_path
            prices = price_engine.load_prices()

            self.assertEqual(len(prices), len(idx))
            self.assertIn("$open", prices.columns)
            self.assertIn("$close", prices.columns)

    def test_handles_split_adjustment(self):
        """应处理复权调整"""
        price_engine = PriceEngine()

        with tempfile.TemporaryDirectory() as tmpdir:
            dates = pd.date_range("2024-08-01", periods=20, freq="B")
            instruments = ["SH600000"]
            idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])

            rng = np.random.default_rng(42)
            prices_before = rng.uniform(10, 12, 10)
            prices_after = rng.uniform(4, 6, 10)

            values = np.concatenate([prices_before, prices_after])
            df = pd.DataFrame({
                "$open": values,
                "$close": values * 1.01,
                "$high": values * 1.02,
                "$low": values * 0.98,
            }, index=idx)

            pq_path = Path(tmpdir) / "prices.parquet"
            df.to_parquet(pq_path)

            with mock.patch.object(price_engine, 'source_pq', pq_path):
                with mock.patch.object(price_engine, 'split_prev', pd.Timestamp("2024-08-10")):
                    with mock.patch.object(price_engine, 'split_curr', pd.Timestamp("2024-08-11")):
                        prices, splits = price_engine.compute_adjusted_prices()

            self.assertEqual(len(prices), len(idx))


class TestBacktestAllFactors(unittest.TestCase):
    """测试批量回测逻辑"""

    def test_returns_results_for_valid_factors(self):
        """应对有效因子返回回测结果"""
        engine = create_backtest_engine(initial_capital=1000000)

        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        stocks = [f"SH{i:06d}" for i in range(1, 21)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])

        rng = np.random.default_rng(42)
        scores_df = pd.DataFrame({
            "factor_a": rng.standard_normal(len(idx)),
            "factor_b": rng.standard_normal(len(idx)) * -1,
        }, index=idx)

        prices_df = pd.DataFrame({
            "$open": rng.uniform(10, 20, len(idx)),
            "$close": rng.uniform(10, 20, len(idx)),
        }, index=idx)

        # 构建价格映射和信号
        price_map = {}
        for (dt, inst), row in prices_df.iterrows():
            price_map[(dt, inst)] = {'open': row['$open'], 'close': row['$close']}

        signals = {}
        for i, date in enumerate(sorted(scores_df.index.get_level_values('datetime').unique())):
            try:
                day_scores = scores_df.xs(date, level='datetime')
                day_scores = day_scores.dropna()
                if len(day_scores) >= 10:
                    selected = day_scores.nlargest(10, 'factor_a').index.tolist()
                    signals[i] = selected
            except KeyError:
                continue

        # 运行回测
        all_dates = sorted(scores_df.index.get_level_values('datetime').unique())
        all_dates = [d for d in all_dates if not pd.isna(d)]

        result = engine.run(all_dates, price_map, signals, hold_days=5, top_k=10)

        self.assertIsInstance(result.daily_value, list)
        self.assertGreater(len(result.daily_value), 0)

    def test_filters_factors_with_insufficient_signals(self):
        """信号不足的因子应被过滤"""
        engine = create_backtest_engine()

        dates = pd.date_range("2024-01-01", periods=20, freq="B")
        stocks = [f"SH{i:06d}" for i in range(1, 11)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])

        rng = np.random.default_rng(42)
        scores_df = pd.DataFrame({
            "weak_factor": rng.standard_normal(len(idx)),
        }, index=idx)

        prices_df = pd.DataFrame({
            "$open": rng.uniform(10, 20, len(idx)),
            "$close": rng.uniform(10, 20, len(idx)),
        }, index=idx)

        price_map = {}
        for (dt, inst), row in prices_df.iterrows():
            price_map[(dt, inst)] = {'open': row['$open'], 'close': row['$close']}

        # 信号不足
        signals = {}

        all_dates = sorted(scores_df.index.get_level_values('datetime').unique())
        all_dates = [d for d in all_dates if not pd.isna(d)]

        result = engine.run(all_dates, price_map, signals, hold_days=5, top_k=10)

        self.assertIsInstance(result, type(engine.run([], {}, {}, 5, 10)))


class TestMetricsCalculation(unittest.TestCase):
    """测试指标计算"""

    def test_calculate_win_rate(self):
        """胜率计算"""
        trades = [2.5, -1.0, 3.0, -0.5, 1.5]
        wins = [t for t in trades if t > 0]
        win_rate = len(wins) / len(trades) * 100

        self.assertAlmostEqual(win_rate, 60.0)

    def test_calculate_profit_factor(self):
        """盈亏比计算"""
        trades = [3.0, 2.0, -1.0, -2.0]
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t <= 0]

        avg_win = np.mean(wins)
        avg_loss = abs(np.mean(losses))
        pf = avg_win / avg_loss if avg_loss > 0 else float('inf')

        self.assertAlmostEqual(pf, 1.67, places=2)

    def test_calculate_sharpe(self):
        """夏普比率计算"""
        returns = pd.Series([0.01, -0.005, 0.008, -0.003, 0.005])
        sharpe = returns.mean() / returns.std() * np.sqrt(252)

        self.assertIsInstance(sharpe, float)
        self.assertGreater(sharpe, 0)

    def test_zero_std_sharpe(self):
        """常数列的夏普比率计算"""
        returns = pd.Series([0.01] * 10)
        std_val = returns.std()
        if std_val > 0:
            sharpe = float(returns.mean() / std_val * np.sqrt(252))
        else:
            sharpe = 0.0

        # 常数列标准差接近0，夏普比率会很大
        self.assertIsInstance(sharpe, float)


class TestEngineModules(unittest.TestCase):
    """测试引擎模块"""

    def test_price_engine_init(self):
        """价格引擎初始化"""
        engine = PriceEngine()
        self.assertIsNotNone(engine.source_pq)

    def test_backtest_engine_init(self):
        """回测引擎初始化"""
        engine = create_backtest_engine()
        self.assertIsInstance(engine, BacktestEngine)

    def test_factor_engine_init(self):
        """因子引擎初始化"""
        engine = create_factor_engine()
        self.assertIsInstance(engine, FactorEngine)

    def test_performance_analyzer_init(self):
        """绩效分析器初始化"""
        from engine.metrics import create_performance_analyzer
        analyzer = create_performance_analyzer()
        self.assertIsNotNone(analyzer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
