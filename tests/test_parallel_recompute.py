#!/usr/bin/env python3
from __future__ import annotations
"""
parallel_recompute_factors.py 测试
"""
import sys
import pandas as pd
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from parallel_recompute_factors import get_sessions, worker_compute


class TestGetSessions:
    def test_get_sessions(self, tmp_path):
        for name in ["session_a", "session_b", "session_c"]:
            session_dir = tmp_path / name
            session_dir.mkdir()
            (session_dir / "factor.py").write_text("df['factor'] = 1\n", encoding="utf-8")
        # session_c 没有 factor.py
        (tmp_path / "session_c" / "factor.py").unlink()

        with patch("parallel_recompute_factors.WS", tmp_path):
            sessions = get_sessions()
            names = [s.name for s in sessions]
            assert "session_a" in names
            assert "session_b" in names
            assert "session_c" not in names
            assert len(names) == 2

    def test_empty_workspace(self, tmp_path):
        with patch("parallel_recompute_factors.WS", tmp_path):
            sessions = get_sessions()
            assert sessions == []


class TestWorkerCompute:
    def test_missing_factor_py(self, tmp_path):
        session = tmp_path / "no_factor"
        session.mkdir()
        name, ok, info = worker_compute(session)
        assert not ok
        assert "无 factor.py" in info

    def test_missing_source_data(self, tmp_path):
        session = tmp_path / "has_factor"
        session.mkdir()
        (session / "factor.py").write_text("x = 1\n", encoding="utf-8")
        with patch("parallel_recompute_factors.SRC_PQ", Path("/nonexistent.parquet")):
            with patch("parallel_recompute_factors.SRC_H5", Path("/nonexistent.h5")):
                name, ok, info = worker_compute(session)
                assert not ok
                assert "源数据不存在" in info

    def test_successful_compute(self, tmp_path):
        """有 parquet 源数据且脚本简单通过安全校验"""
        session = tmp_path / "good_factor"
        session.mkdir()
        (session / "factor.py").write_text("x = 1\n", encoding="utf-8")
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = ["SH600000"]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        src_df = pd.DataFrame({"close": [1.0] * 5}, index=idx)
        src_pq = tmp_path / "daily_pv.parquet"
        src_df.to_parquet(src_pq)
        res_df = pd.DataFrame({"factor_x": [0.0] * 5}, index=idx)
        res_df.to_hdf(session / "result.h5", key="data", mode="w")

        with patch("parallel_recompute_factors.SRC_PQ", src_pq):
            with patch("parallel_recompute_factors.SRC_H5", Path("/nonexistent.h5")):
                name, ok, info = worker_compute(session)
                assert ok

    def test_factor_script_failure(self, tmp_path):
        """因子脚本被安全校验拦截"""
        session = tmp_path / "bad_factor"
        session.mkdir()
        (session / "factor.py").write_text(
            "import os\nos.system('echo')\n",
            encoding="utf-8",
        )
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = ["SH600000"]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        src_df = pd.DataFrame({"close": [1.0] * 5}, index=idx)
        src_pq = tmp_path / "daily_pv.parquet"
        src_df.to_parquet(src_pq)

        with patch("parallel_recompute_factors.SRC_PQ", src_pq):
            with patch("parallel_recompute_factors.SRC_H5", Path("/nonexistent.h5")):
                name, ok, info = worker_compute(session)
                assert not ok
                assert "安全校验" in info

    def test_no_result_file(self, tmp_path):
        """因子执行成功但无结果文件"""
        session = tmp_path / "no_result"
        session.mkdir()
        (session / "factor.py").write_text("pass\n", encoding="utf-8")
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = ["SH600000"]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        src_df = pd.DataFrame({"close": [1.0] * 5}, index=idx)
        src_pq = tmp_path / "daily_pv.parquet"
        src_df.to_parquet(src_pq)

        with patch("parallel_recompute_factors.SRC_PQ", src_pq):
            with patch("parallel_recompute_factors.SRC_H5", Path("/nonexistent.h5")):
                name, ok, info = worker_compute(session)
                assert not ok
                assert "无结果" in info or "result" in info.lower()
