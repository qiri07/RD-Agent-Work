"""stock_analyzer/analyzer.py 全覆盖测试（函数级）。

该模块不包含类，仅有纯函数。测试覆盖：
  - compute_factors 各因子计算分支
  - compute_returns
  - compute_stats 正常 / 单元素 / 空
  - compute_yearly_stats
  - compute_ic_records
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats as scipy_stats

from stock_analyzer.analyzer import (
    compute_factors,
    compute_returns,
    compute_stats,
    compute_yearly_stats,
    compute_ic_records,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


def _make_stock_df(n: int = 300) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "$close": close,
        "$open": close * 0.99,
        "$high": close * 1.01,
        "$low": close * 0.99,
        "$volume": np.abs(np.random.randn(n)) * 1e6 + 1e5,
    })
    df.index = pd.MultiIndex.from_tuples(
        [(d, "SH600519") for d in dates], names=["date", "instrument"]
    )
    return df


def _make_market_df(n: int = 300) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "date": dates,
        "$close": 3500.0 + np.cumsum(np.random.randn(n) * 10),
    })


# ── compute_factors ──────────────────────────────────────────────────────────


class TestComputeFactors:
    def test_returns_dataframe_with_expected_columns(self) -> None:
        stock = _make_stock_df(300)
        market = _make_market_df(300)
        result = compute_factors(stock, market)
        assert isinstance(result, pd.DataFrame)
        assert "momentum_5d" in result.columns
        assert "reversal_5d" in result.columns
        assert "volatility_10d" in result.columns
        assert "rsi_14" in result.columns
        assert "macd" in result.columns
        assert "bollinger_pos" in result.columns
        assert "alpha_20d" in result.columns

    def test_momentum_5d_calculation(self) -> None:
        stock = _make_stock_df(20)
        market = _make_market_df(20)
        result = compute_factors(stock, market)
        # momentum_5d = close / close.shift(5) - 1
        expected = stock["$close"] / stock["$close"].shift(5) - 1
        pd.testing.assert_series_equal(
            result["momentum_5d"].dropna(), expected.dropna(), check_names=False
        )

    def test_rsi_bounded(self) -> None:
        stock = _make_stock_df(50)
        market = _make_market_df(50)
        result = compute_factors(stock, market)
        rsi = result["rsi_14"].dropna()
        assert (rsi >= 0).all()
        assert (rsi <= 100).all()

    def test_short_series(self) -> None:
        """短序列不报错，仅返回 NaN。"""
        stock = _make_stock_df(10)
        market = _make_market_df(10)
        result = compute_factors(stock, market)
        assert len(result) == 10

    def test_alpha_20d_finite(self) -> None:
        stock = _make_stock_df(300)
        market = _make_market_df(300)
        result = compute_factors(stock, market)
        alpha = result["alpha_20d"].dropna()
        assert len(alpha) > 0
        assert not alpha.isna().any()


# ── compute_returns ──────────────────────────────────────────────────────────


class TestComputeReturns:
    def test_adds_ret_columns(self) -> None:
        stock = _make_stock_df(30).reset_index()
        result = compute_returns(stock)
        assert "ret_1d" in result.columns
        assert "ret_5d" in result.columns

    def test_ret_values_correct(self) -> None:
        stock = _make_stock_df(10).reset_index()
        result = compute_returns(stock)
        expected_1d = stock["$close"].pct_change(1)
        pd.testing.assert_series_equal(
            result["ret_1d"].dropna(), expected_1d.dropna(), check_names=False
        )


# ── compute_stats ────────────────────────────────────────────────────────────


class TestComputeStats:
    def test_normal_series(self) -> None:
        rets = pd.Series(np.random.randn(252) * 0.02)
        result = compute_stats(rets)
        assert "ann_ret" in result
        assert "ann_vol" in result
        assert "sharpe" in result
        assert "max_dd" in result
        assert result["max_dd"] <= 0  # 回撤 <= 0

    def test_constant_returns(self) -> None:
        rets = pd.Series([0.01] * 252)
        result = compute_stats(rets)
        assert result["ann_ret"] > 0
        assert result["sharpe"] >= 0  # vol=0 → sharpe=0（代码保护）
        assert result["max_dd"] == 0.0

    def test_empty_series(self) -> None:
        rets = pd.Series([], dtype=float)
        result = compute_stats(rets)
        assert result["ann_ret"] == 0.0
        assert result["sharpe"] == 0.0

    def test_single_element(self) -> None:
        rets = pd.Series([0.02])
        result = compute_stats(rets)
        assert isinstance(result["ann_ret"], float)


# ── compute_yearly_stats ─────────────────────────────────────────────────────


class TestComputeYearlyStats:
    def test_two_full_years(self) -> None:
        dates = pd.date_range("2024-01-01", periods=500, freq="D")
        df = pd.DataFrame({
            "date": dates,
            "instrument": ["SH600519"] * 500,
            "ret_1d": np.random.randn(500) * 0.02,
        })
        result = compute_yearly_stats(df)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "year" in result[0]
        assert "return_pct" in result[0]

    def test_year_with_insufficient_days_skipped(self) -> None:
        """年度交易天数 < 100 → 跳过。"""
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        df = pd.DataFrame({
            "date": dates,
            "instrument": ["SH600519"] * 50,
            "ret_1d": np.random.randn(50) * 0.02,
        })
        result = compute_yearly_stats(df)
        assert result == []

    def test_empty_df(self) -> None:
        df = pd.DataFrame({
            "date": pd.to_datetime([]),
            "instrument": pd.Series([], dtype=str),
            "ret_1d": pd.Series([], dtype=float),
        })
        result = compute_yearly_stats(df)
        assert result == []


# ── compute_ic_records ───────────────────────────────────────────────────────


class TestComputeIcRecords:
    def test_returns_records_for_valid_factors(self) -> None:
        n = 300
        dates = pd.date_range("2025-01-01", periods=n, freq="D")
        idx = pd.MultiIndex.from_tuples([(d, "SH600519") for d in dates], names=["date", "instrument"])
        factor_df = pd.DataFrame({
            "momentum_5d": np.random.randn(n),
            "rsi_14": np.random.randn(n),
            "unknown_col": np.random.randn(n),
        }, index=idx)
        forward_ret = pd.Series(np.random.randn(n), index=idx, name="forward_ret")
        records = compute_ic_records(factor_df, forward_ret)
        assert isinstance(records, list)
        assert len(records) >= 2  # momentum_5d + rsi_14（>=100样本）
        for rec in records:
            assert "factor" in rec
            assert "IC" in rec
            assert "p_value" in rec

    def test_insufficient_samples_skipped(self) -> None:
        n = 50
        dates = pd.date_range("2025-01-01", periods=n, freq="D")
        idx = pd.MultiIndex.from_tuples([(d, "SH600519") for d in dates], names=["date", "instrument"])
        factor_df = pd.DataFrame({"momentum_5d": np.random.randn(n)}, index=idx)
        forward_ret = pd.Series(np.random.randn(n), index=idx, name="forward_ret")
        records = compute_ic_records(factor_df, forward_ret)
        assert records == []  # < 100 样本跳过

    def test_empty_factor_df(self) -> None:
        factor_df = pd.DataFrame(columns=["momentum_5d"])
        factor_df.index = pd.MultiIndex.from_tuples([], names=["date", "instrument"])
        forward_ret = pd.Series([], dtype=float)
        records = compute_ic_records(factor_df, forward_ret)
        assert records == []
