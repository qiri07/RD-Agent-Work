#!/usr/bin/env python3
from __future__ import annotations
"""
factor_stock_selection.py 测试
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import factor_stock_selection as fsel
import config as cfg


class TestLoadFactor:
    def test_load_standard_index(self, tmp_path):
        original_ws = fsel.WORKSPACE
        try:
            fsel.WORKSPACE = tmp_path
            factor_dir = tmp_path / "test_factor"
            factor_dir.mkdir()
            dates = pd.date_range("2024-01-01", periods=3)
            instruments = ["SH600000", "SZ000001"]
            idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
            df = pd.DataFrame({"test_f": [1, 2, 3, 4, 5, 6]}, index=idx)
            df.to_hdf(factor_dir / "result.h5", key="data", mode="w")

            result_df, fname = fsel.load_factor("test_factor")
            assert fname == "test_f"
            assert result_df.index.names == ["datetime", "instrument"]
            assert len(result_df) == 6
        finally:
            fsel.WORKSPACE = original_ws

    def test_load_instrument_date_reversed(self, tmp_path):
        original_ws = fsel.WORKSPACE
        try:
            fsel.WORKSPACE = tmp_path
            factor_dir = tmp_path / "rev_factor"
            factor_dir.mkdir()
            dates = pd.date_range("2024-01-01", periods=3)
            instruments = ["SH600000", "SZ000001"]
            idx = pd.MultiIndex.from_product([instruments, dates], names=["instrument", "date"])
            df = pd.DataFrame({"test_f": [1, 2, 3, 4, 5, 6]}, index=idx)
            df.to_hdf(factor_dir / "result.h5", key="data", mode="w")

            result_df, fname = fsel.load_factor("rev_factor")
            assert result_df.index.names == ["datetime", "instrument"]
        finally:
            fsel.WORKSPACE = original_ws

    def test_load_none_index_names_sh_prefix(self, tmp_path):
        original_ws = fsel.WORKSPACE
        try:
            fsel.WORKSPACE = tmp_path
            factor_dir = tmp_path / "none_idx"
            factor_dir.mkdir()
            dates = pd.date_range("2024-01-01", periods=2)
            instruments = ["SH600000", "SZ000001"]
            idx = pd.MultiIndex.from_product([instruments, dates], names=[None, None])
            df = pd.DataFrame({"test_f": [1, 2, 3, 4]}, index=idx)
            df.to_hdf(factor_dir / "result.h5", key="data", mode="w")

            result_df, fname = fsel.load_factor("none_idx")
            assert result_df.index.names == ["datetime", "instrument"]
        finally:
            fsel.WORKSPACE = original_ws


class TestStandardize:
    def test_basic_standardize(self):
        df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50]})
        result = fsel.standardize(df)
        # standardize() 使用样本标准差 (ddof=1)，验证均值接近0且标准差接近1
        for col in result.columns:
            assert abs(result[col].mean()) < 1e-10
            assert abs(result[col].std(ddof=1) - 1.0) < 1e-10

    def test_zero_std_column(self):
        df = pd.DataFrame({"a": [5, 5, 5], "b": [1, 2, 3]})
        result = fsel.standardize(df)
        assert (result["a"] == 0).all()
        assert result["b"].std() > 0

    def test_empty_df(self):
        df = pd.DataFrame()
        result = fsel.standardize(df)
        assert result.empty

    def test_single_value(self):
        df = pd.DataFrame({"a": [42.0]})
        result = fsel.standardize(df)
        # 单值标准化后应为 0（std=NaN，被处理为 0）
        assert pd.isna(result["a"].iloc[0]) or result["a"].iloc[0] == 0


class TestScreenSingleFactor:
    def setup_method(self):
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = [f"SH60000{i}" for i in range(5)]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        self.df = pd.DataFrame({"value": list(range(25))}, index=idx)

    def test_default_top_k(self):
        top10, date = fsel.screen_single_factor(self.df, "value", top_k=10)
        assert len(top10) <= 10
        assert date is not None

    def test_specific_top_k(self):
        top5, date = fsel.screen_single_factor(self.df, "value", top_k=5)
        assert len(top5) <= 5

    def test_specific_date(self):
        target_date = pd.Timestamp("2024-01-03")
        top10, date = fsel.screen_single_factor(self.df, "value", top_k=3, date=target_date)
        assert date == pd.Timestamp("2024-01-03")
        assert len(top10) <= 3

    def test_date_before_data(self):
        target_date = pd.Timestamp("2020-01-01")
        top10, date = fsel.screen_single_factor(self.df, "value", top_k=3, date=target_date)
        assert date == pd.Timestamp("2024-01-01")

    def test_ranking_correct(self):
        top10, _ = fsel.screen_single_factor(self.df, "value", top_k=3)
        assert top10.iloc[0]["rank"] == 1.0


class TestScreenMultiFactor:
    def setup_method(self):
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = [f"SH60000{i}" for i in range(5)]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        self.df = pd.DataFrame({
            "factor_a": list(range(25)),
            "factor_b": list(range(25, 50)),
        }, index=idx)

    def test_default_weights(self):
        top10, date, weights = fsel.screen_multi_factor(self.df, top_k=5)
        assert len(top10) <= 5
        assert date is not None
        assert abs(sum(weights.values()) - 1.0) < 1e-10

    def test_custom_weights(self):
        weights = {"factor_a": 0.7, "factor_b": 0.3}
        top10, date, used_weights = fsel.screen_multi_factor(self.df, top_k=3, weights=weights)
        assert len(top10) <= 3
        assert abs(used_weights["factor_a"] - 0.7) < 1e-10
        assert abs(used_weights["factor_b"] - 0.3) < 1e-10

    def test_specific_date(self):
        target_date = pd.Timestamp("2024-01-03")
        top10, date, _ = fsel.screen_multi_factor(self.df, top_k=3, date=target_date)
        assert date == pd.Timestamp("2024-01-03")
