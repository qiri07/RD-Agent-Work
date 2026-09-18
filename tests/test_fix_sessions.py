#!/usr/bin/env python3
from __future__ import annotations
"""
fix_sessions.py 测试
"""
import sys
import time
import pandas as pd
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from fix_sessions import regen_h5_for_session, recompute_factor_for_session


class TestRegenH5ForSession:
    def test_regenerate_h5(self, tmp_path):
        sid = tmp_path / "test_session"
        sid.mkdir()
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = ["SH600000", "SZ000001"]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        df = pd.DataFrame({"close": list(range(10))}, index=idx)
        pq_path = sid / "daily_pv.parquet"
        h5_path = sid / "daily_pv.h5"
        df.to_parquet(pq_path)
        time.sleep(0.05)
        df.to_hdf(h5_path, key="data", mode="w")
        # 更新 parquet 使其比 h5 新
        df["close"] = list(range(10, 20))
        df.to_parquet(pq_path)

        with patch("fix_sessions.ws", tmp_path):
            ok_name, ok, info = regen_h5_for_session("test_session")
            assert ok

    def test_skip_if_up_to_date(self, tmp_path):
        sid = tmp_path / "skip_session"
        sid.mkdir()
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = ["SH600000"]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        df = pd.DataFrame({"close": [1] * 5}, index=idx)
        pq_path = sid / "daily_pv.parquet"
        h5_path = sid / "daily_pv.h5"
        df.to_parquet(pq_path)
        time.sleep(0.1)
        df.to_hdf(h5_path, key="data", mode="w")

        with patch("fix_sessions.ws", tmp_path):
            ok_name, ok, info = regen_h5_for_session("skip_session")
            assert ok
            assert "up-to-date" in info.lower() or "skipped" in info.lower()

    def test_missing_files(self, tmp_path):
        sid = tmp_path / "missing"
        sid.mkdir()
        with patch("fix_sessions.ws", tmp_path):
            ok_name, ok, info = regen_h5_for_session("missing")
            assert not ok
            assert "missing" in info.lower()

    def test_missing_parquet(self, tmp_path):
        sid = tmp_path / "no_pq"
        sid.mkdir()
        dates = pd.date_range("2024-01-01", periods=3)
        idx = pd.MultiIndex.from_product([dates, ["SH600000"]], names=["datetime", "instrument"])
        df = pd.DataFrame({"close": [1, 2, 3]}, index=idx)
        h5_path = sid / "daily_pv.h5"
        df.to_hdf(h5_path, key="data", mode="w")

        with patch("fix_sessions.ws", tmp_path):
            ok_name, ok, info = regen_h5_for_session("no_pq")
            assert not ok
            assert "missing" in info.lower()


class TestRecomputeFactorForSession:
    def test_recompute_success(self, tmp_path):
        """因子重算成功：脚本通过安全校验，已有 result.h5"""
        sid = tmp_path / "recomp_session"
        sid.mkdir()
        # 简单脚本，不依赖 df
        (sid / "factor.py").write_text("x = 1\n", encoding="utf-8")
        dates = pd.date_range("2024-01-01", periods=5)
        instruments = ["SH600000", "SZ000001"]
        idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        df = pd.DataFrame({"factor_test": [0.0] * 10}, index=idx)
        df.to_hdf(sid / "result.h5", key="data", mode="w")

        with patch("fix_sessions.ws", tmp_path):
            ok_name, ok, info = recompute_factor_for_session("recomp_session")
            assert ok

    def test_missing_factor_py(self, tmp_path):
        """没有 factor.py 时返回失败"""
        sid = tmp_path / "no_factor"
        sid.mkdir()
        with patch("fix_sessions.ws", tmp_path):
            ok_name, ok, info = recompute_factor_for_session("no_factor")
            assert not ok
            assert "no factor.py" in info.lower() or "无 factor.py" in info

    def test_no_result_file(self, tmp_path):
        """factor.py 存在但无 result.h5"""
        sid = tmp_path / "no_result"
        sid.mkdir()
        (sid / "factor.py").write_text("pass\n", encoding="utf-8")
        with patch("fix_sessions.ws", tmp_path):
            ok_name, ok, info = recompute_factor_for_session("no_result")
            assert not ok
            assert "no result" in info.lower() or "无结果" in info

    def test_exception_handled(self, tmp_path):
        """执行异常时返回错误信息"""
        sid = tmp_path / "error_session"
        sid.mkdir()
        (sid / "factor.py").write_text(
            "import os\nos.system('echo')\n",
            encoding="utf-8",
        )
        with patch("fix_sessions.ws", tmp_path):
            ok_name, ok, info = recompute_factor_for_session("error_session")
            assert not ok
            assert len(info) > 0
