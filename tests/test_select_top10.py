#!/usr/bin/env python3
from __future__ import annotations
"""
select_top10.py 测试
"""
import sys
import pandas as pd
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import select_top10
import config as cfg


class TestLoadICResults:
    def test_load_from_csv(self, tmp_path, monkeypatch):
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2", "f3"],
            "IC_5d": [0.05, -0.03, 0.07],
            "IC_t_5d": [2.1, -1.5, 3.0],
        })
        ic_path = tmp_path / "ic_scan_results_new.csv"
        ic_df.to_csv(ic_path, index=False)
        monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
        result = select_top10.load_ic_results()
        assert len(result) == 3
        assert set(result.columns) & {"factor_id", "IC_5d"}

    def test_missing_csv_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
        with pytest.raises(FileNotFoundError):
            select_top10.load_ic_results()


class TestLoadFactors:
    def test_load_from_h5(self, tmp_path, monkeypatch):
        factor_dir = tmp_path / "test_factor"
        factor_dir.mkdir()
        dates = pd.date_range("2024-01-01", periods=3)
        instruments = ["SH600000", "SZ000001"]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        df = pd.DataFrame({"test_factor": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=idx)
        df.to_hdf(factor_dir / "result.h5", key="data", mode="w")

        monkeypatch.setattr(cfg, "RDAGENT_WORKSPACE", tmp_path)
        result = select_top10.load_factors(["test_factor"])
        assert "test_factor" in result
        assert len(result["test_factor"]) == 6

    def test_missing_h5_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "RDAGENT_WORKSPACE", tmp_path)
        result = select_top10.load_factors(["nonexistent_factor"])
        assert result == {}

    def test_empty_factor_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "RDAGENT_WORKSPACE", tmp_path)
        result = select_top10.load_factors([])
        assert result == {}


class TestScreenTop10:
    def test_screen_top10_success(self, tmp_path, monkeypatch):
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2"],
            "IC_5d": [0.05, 0.03],
            "IC_t_5d": [2.0, 1.5],
            "_abs_ic": [0.05, 0.03],
        })
        ic_path = tmp_path / "ic_scan_results_new.csv"
        ic_df.to_csv(ic_path, index=False)

        factor_dir1 = tmp_path / "f1"
        factor_dir1.mkdir()
        factor_dir2 = tmp_path / "f2"
        factor_dir2.mkdir()
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = [f"SH60000{i}" for i in range(5)]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        # 注意：load_factors 读取 h5 时列名是因子名，不是目录名
        df1 = pd.DataFrame({"f1": list(range(25))}, index=idx)
        df2 = pd.DataFrame({"f2": list(range(25, 50))}, index=idx)
        df1.to_hdf(factor_dir1 / "result.h5", key="data", mode="w")
        df2.to_hdf(factor_dir2 / "result.h5", key="data", mode="w")

        monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(cfg, "RDAGENT_WORKSPACE", tmp_path)

        stocks, latest_date = select_top10.screen_top10(ic_df, top_n=2)
        assert len(stocks) <= 10
        assert latest_date is not None

    def test_no_factor_data_raises(self, tmp_path, monkeypatch):
        ic_df = pd.DataFrame({
            "factor_id": ["nonexistent"],
            "IC_5d": [0.05],
            "IC_t_5d": [2.0],
            "_abs_ic": [0.05],
        })
        ic_path = tmp_path / "ic_scan_results_new.csv"
        ic_df.to_csv(ic_path, index=False)
        monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(cfg, "RDAGENT_WORKSPACE", tmp_path)
        with pytest.raises(RuntimeError, match="没有可用的因子数据"):
            select_top10.screen_top10(ic_df, top_n=1)


class TestPushToFeishu:
    @pytest.mark.parametrize("success", [True, False])
    def test_push_result(self, success):
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2"],
            "IC_5d": [0.05, 0.03],
            "IC_t_5d": [2.0, 1.5],
            "_abs_ic": [0.05, 0.03],
        })
        stocks_df = pd.DataFrame({
            "rank": [1, 2],
            "instrument": ["SH600000", "SZ000001"],
            "composite_score": [0.9, 0.8],
        })
        latest_date = pd.Timestamp("2024-09-12")

        with patch("select_top10.send_feishu") as mock_send:
            mock_send.return_value = success
            result = select_top10.push_to_feishu(ic_df, stocks_df, latest_date)
            assert result == success
            mock_send.assert_called_once()
