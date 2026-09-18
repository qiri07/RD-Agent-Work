"""stock_analyzer/backtest.py 全覆盖测试。

覆盖：
  - Backtest.buy / sell / value
  - run_bt 四种策略：momentum / mean_reversion / rsi / macd
  - run_all_backtests 多策略组合
  - 买入资金不足场景
  - 最后一天强制平仓
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.backtest import Backtest, run_bt, run_all_backtests, STRATEGY_CONFIG


# ── fixtures ─────────────────────────────────────────────────────────────────


def _make_stock_df(dates: list[str], prices: list[float]) -> pd.DataFrame:
    instruments = ["SH600519"] * len(dates)
    data = {
        "date": pd.to_datetime(dates),
        "instrument": instruments,
        "$open": prices,
        "$close": prices,
        "$high": [p * 1.01 for p in prices],
        "$low": [p * 0.99 for p in prices],
        "$volume": [1e6] * len(dates),
    }
    df = pd.DataFrame(data)
    return df.set_index(["date", "instrument"]).sort_index()


def _make_factor_df(dates: list[str], values: list[float], col_name: str = "factor") -> pd.DataFrame:
    instruments = ["SH600519"] * len(dates)
    data = {
        "date": pd.to_datetime(dates),
        "instrument": instruments,
        col_name: values,
    }
    df = pd.DataFrame(data)
    return df.set_index(["date", "instrument"]).sort_index()


# ── Backtest class ───────────────────────────────────────────────────────────


class TestBacktestClass:
    def test_init_default_values(self) -> None:
        bt = Backtest()
        assert bt.cash > 0
        assert bt.shares == 0
        assert bt.trades == []
        assert bt.daily == []

    def test_buy_success(self) -> None:
        bt = Backtest()
        result = bt.buy("2026-08-01", 100.0, 100)
        assert result is True
        assert bt.shares == 100
        assert len(bt.trades) == 1
        assert bt.trades[0]["action"] == "BUY"

    def test_buy_insufficient_funds(self) -> None:
        bt = Backtest()
        # 用掉全部现金后再买
        bt.buy("2026-08-01", bt.cash * 0.99, 1)
        result = bt.buy("2026-08-02", 100.0, 1000000)
        assert result is False
        assert bt.shares == 1  # 未增加

    def test_sell(self) -> None:
        bt = Backtest()
        bt.buy("2026-08-01", 100.0, 100)
        result = bt.sell("2026-08-02", 110.0, 100)
        assert result is True
        assert bt.shares == 0
        assert bt.trades[-1]["action"] == "SELL"

    def test_value(self) -> None:
        bt = Backtest()
        bt.buy("2026-08-01", 100.0, 100)
        val = bt.value("2026-08-02", 105.0)
        assert val > bt.cash  # 含持仓市值


# ── run_bt ───────────────────────────────────────────────────────────────────


class TestRunBt:
    def test_momentum_strategy_buy_then_sell(self) -> None:
        dates = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"]
        prices = [100.0, 101.0, 102.0, 103.0, 104.0]
        stock_df = _make_stock_df(dates, prices)
        # 因子值：前低后高，触发 momentum 买入
        factor_df = _make_factor_df(dates, [0.005, 0.01, 0.02, -0.01, -0.02], "momentum_5d")
        bt = run_bt(stock_df, factor_df, "momentum_5d", "momentum", {"threshold": 0.01})
        assert isinstance(bt, Backtest)
        assert len(bt.trades) > 0

    def test_mean_reversion_strategy(self) -> None:
        dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
        prices = [100.0, 100.0, 100.0]
        stock_df = _make_stock_df(dates, prices)
        factor_df = _make_factor_df(dates, [-0.05, 0.05, 0.0], "reversal_5d")
        bt = run_bt(stock_df, factor_df, "reversal_5d", "mean_reversion", {"threshold": 0.03})
        assert isinstance(bt, Backtest)

    def test_rsi_strategy(self) -> None:
        dates = ["2026-07-" + str(i).zfill(2) for i in range(1, 26)]
        prices = [100.0 + i * 0.1 for i in range(25)]
        stock_df = _make_stock_df(dates, prices)
        # 手动构造 RSI 因子：先低后高
        factor_df = _make_factor_df(dates, [20.0, 25.0, 35.0, 50.0, 75.0] + [50.0] * 20, "rsi_14")
        bt = run_bt(stock_df, factor_df, "rsi_14", "rsi", {})
        assert isinstance(bt, Backtest)

    def test_macd_strategy(self) -> None:
        dates = ["2026-07-" + str(i).zfill(2) for i in range(1, 26)]
        prices = [100.0 + i * 0.05 for i in range(25)]
        stock_df = _make_stock_df(dates, prices)
        factor_df = _make_factor_df(dates, [0.1, 0.2, 0.3, -0.1, -0.2] + [0.0] * 20, "macd")
        # macd_signal 列也需提供
        sig_df = _make_factor_df(dates, [0.05, 0.1, 0.15, 0.0, -0.1] + [0.0] * 20, "macd_signal")
        combined = pd.concat([pd.DataFrame({"macd": factor_df["macd"]}, index=factor_df.index), sig_df], axis=1)
        bt = run_bt(stock_df, combined, "macd", "macd", {})
        assert isinstance(bt, Backtest)

    def test_nan_factor_skips_day(self) -> None:
        dates = ["2026-07-01", "2026-07-02"]
        prices = [100.0, 101.0]
        stock_df = _make_stock_df(dates, prices)
        factor_df = _make_factor_df(dates, [np.nan, 0.02], "momentum_5d")
        bt = run_bt(stock_df, factor_df, "momentum_5d", "momentum", {"threshold": 0.01})
        # 第一天因子 NaN 跳过，第二天因子 0.02 > 0.01 → 买入；最后一天强制平仓 → 卖出
        assert len(bt.trades) == 2

    def test_last_day_forced_close(self) -> None:
        dates = ["2026-07-01", "2026-07-02"]
        prices = [100.0, 101.0]
        stock_df = _make_stock_df(dates, prices)
        factor_df = _make_factor_df(dates, [0.03, 0.03], "momentum_5d")
        bt = run_bt(stock_df, factor_df, "momentum_5d", "momentum", {"threshold": 0.01})
        # 最后一天有持仓时强制卖出
        sell_count = sum(1 for t in bt.trades if t["action"] == "SELL")
        assert sell_count >= 1

    def test_no_matching_rows_skips(self) -> None:
        """merge 结果为空行时跳过。"""
        dates = ["2026-07-01"]
        stock_df = _make_stock_df(dates, [100.0])
        # 不同 instrument 导致 merge 无交集
        factor_df = _make_factor_df(dates, [0.02], "momentum_5d")
        factor_df.index = factor_df.index.set_levels(["SH999999"], level="instrument")
        bt = run_bt(stock_df, factor_df, "momentum_5d", "momentum", {"threshold": 0.01})
        assert isinstance(bt, Backtest)


# ── run_all_backtests ────────────────────────────────────────────────────────


class TestRunAllBacktests:
    def test_runs_all_strategies(self) -> None:
        dates = ["2026-07-" + str(i).zfill(2) for i in range(1, 31)]
        prices = [100.0 + i * 0.1 for i in range(30)]
        stock_df = _make_stock_df(dates, prices)
        factor_df = _make_factor_df(
            dates,
            [0.02] * 30,
            "momentum_5d",
        )
        # 同时提供多个因子列
        factor_df["rsi_14"] = [30.0] * 15 + [70.0] * 15
        factor_df["macd"] = [0.1] * 30
        factor_df["macd_signal"] = [0.05] * 30

        results = run_all_backtests(stock_df, factor_df)
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert "strategy" in r
            assert "return_pct" in r

    def test_missing_factor_column_skipped(self) -> None:
        dates = ["2026-07-01"]
        stock_df = _make_stock_df(dates, [100.0])
        factor_df = _make_factor_df(dates, [0.02], "other_factor")
        results = run_all_backtests(stock_df, factor_df)
        assert results == []
