#!/usr/bin/env python3
"""
factor_portfolio.py 测试
"""
import sys
import pandas as pd
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from factor_portfolio import FactorPortfolio


class TestFactorPortfolio:
    def setup_method(self):
        """创建临时因子数据"""
        self.tmpdir = Path(__file__).parent.parent / "tmp_test_portfolio"
        self.tmpdir.mkdir(exist_ok=True)
        self.portfolio = FactorPortfolio(workspace_path=str(self.tmpdir))

        # 创建两个因子文件
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = ["SH600000", "SZ000001", "SH600002"]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])

        for fid, fname, values in [
            ("f1", "factor_a", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]),
            ("f2", "factor_b", [5.0, 4.0, 3.0, 2.0, 1.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]),
        ]:
            factor_dir = self.tmpdir / fid
            factor_dir.mkdir(exist_ok=True)
            df = pd.DataFrame({fname: values}, index=idx)
            df.to_hdf(factor_dir / "result.h5", key="data", mode="w")

    def teardown_method(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def test_load_multiple_factors(self):
        result = self.portfolio.load_multiple_factors(["f1", "f2"], normalize=False)
        assert result is not None
        assert len(result.columns) == 2
        assert "factor_a" in result.columns
        assert "factor_b" in result.columns

    def test_load_missing_factor(self):
        result = self.portfolio.load_multiple_factors(["f1", "nonexistent"])
        assert result is not None
        assert len(result.columns) == 1

    def test_load_no_factors(self):
        result = self.portfolio.load_multiple_factors(["nonexistent"])
        assert result is None

    def test_normalize_factors(self):
        combined = self.portfolio.load_multiple_factors(["f1", "f2"], normalize=False)
        normalized = self.portfolio._normalize_factors(combined)
        # 标准化后方差应接近 1
        for col in normalized.columns:
            assert abs(normalized[col].std() - 1.0) < 0.01 or normalized[col].std() == 0

    def test_calculate_factor_score_equal_weight(self):
        combined = self.portfolio.load_multiple_factors(["f1", "f2"], normalize=False)
        score = self.portfolio.calculate_factor_score(combined)
        assert isinstance(score, pd.Series)
        assert len(score) == len(combined)

    def test_calculate_factor_score_custom_weight(self):
        combined = self.portfolio.load_multiple_factors(["f1", "f2"], normalize=False)
        weights = {"factor_a": 0.7, "factor_b": 0.3}
        score = self.portfolio.calculate_factor_score(combined, weights=weights)
        assert isinstance(score, pd.Series)

    def test_calculate_factor_score_missing_factor_in_weights(self):
        """权重中包含不存在的因子，应跳过并给出警告"""
        combined = self.portfolio.load_multiple_factors(["f1"], normalize=False)
        weights = {"factor_a": 0.5, "nonexistent": 0.5}
        score = self.portfolio.calculate_factor_score(combined, weights=weights)
        assert score is not None

    def test_backtest_factor(self):
        combined = self.portfolio.load_multiple_factors(["f1"], normalize=False)
        result = self.portfolio.backtest_factor(combined, top_k=2)
        assert result is not None
        assert "selected_stocks" in result.columns

    def test_backtest_factor_empty(self):
        """因子数据过少时返回 None"""
        dates = pd.date_range("2024-01-01", periods=2)
        instruments = ["SH600000"]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        df = pd.DataFrame({"small": [1.0, 2.0]}, index=idx)
        result = self.portfolio.backtest_factor(df, top_k=10)
        assert result is None
