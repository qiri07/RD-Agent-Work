"""engine/ic_scan/data.py 全覆盖测试。

覆盖：
  - load_returns_from_sessions 空 sessions
  - load_returns_from_sessions 正常路径
  - load_returns_from_sessions 异常跳过
  - validate_data_consistency 一致 / 不一致
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from engine.ic_scan.data import load_returns_from_sessions, validate_data_consistency


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_session_pq(ws: Path, name: str, n_dates: int = 20) -> Path:
    session_dir = ws / name
    session_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2026-01-01", periods=n_dates, freq="D")
    df = pd.DataFrame({
        "date": dates,
        "instrument": ["SH600519", "SZ000001"] * (n_dates // 2),
        "$close": [100.0 + i * 0.1 for i in range(n_dates)],
    })
    df = df.set_index(["date", "instrument"]).sort_index()
    pq_path = session_dir / "daily_pv.parquet"
    df.to_parquet(pq_path)
    return pq_path


# ── load_returns_from_sessions ───────────────────────────────────────────────


class TestLoadReturnsFromSessions:
    def test_empty_sessions(self) -> None:
        result = load_returns_from_sessions([])
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_single_session(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        _make_session_pq(ws, "session1")
        result = load_returns_from_sessions([ws / "session1"])
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        assert "return_1d" in result.columns
        assert "return_5d" in result.columns

    def test_multiple_sessions_combined(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        _make_session_pq(ws, "session1", n_dates=20)
        _make_session_pq(ws, "session2", n_dates=20)
        result = load_returns_from_sessions([ws / "session1", ws / "session2"])
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    def test_session_missing_parquet_skipped(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        missing = ws / "missing"
        missing.mkdir()
        # 无 daily_pv.parquet
        result = load_returns_from_sessions([missing])
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_session_read_error_skipped(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        bad = ws / "bad"
        bad.mkdir()
        (bad / "daily_pv.parquet").write_text("not parquet", encoding="utf-8")
        good = ws / "good"
        good.mkdir()
        _make_session_pq(good, "good")
        result = load_returns_from_sessions([bad, good / "good"])
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0


# ── validate_data_consistency ────────────────────────────────────────────────


class TestValidateDataConsistency:
    def test_perfect_match(self) -> None:
        dates = pd.date_range("2026-01-01", periods=200, freq="D")
        factor_idx = pd.MultiIndex.from_tuples(
            [(d, "SH600519") for d in dates],
            names=["datetime", "instrument"],
        )
        factor_results = {"mom5": pd.Series(np.ones(200), index=factor_idx)}
        returns_df = pd.DataFrame({"return_5d": np.random.randn(200)}, index=factor_idx)
        result = validate_data_consistency(factor_results, returns_df)
        assert result is True

    def test_low_match_rate_returns_false(self) -> None:
        """共同样本 < 90% → False。"""
        dates_factor = pd.date_range("2026-01-01", periods=200, freq="D")
        factor_idx = pd.MultiIndex.from_tuples(
            [(d, "SH600519") for d in dates_factor],
            names=["datetime", "instrument"],
        )
        factor_results = {"mom5": pd.Series(np.ones(200), index=factor_idx)}
        # 只有 50% 的日期匹配
        dates_ret = pd.date_range("2026-06-01", periods=100, freq="D")
        ret_idx = pd.MultiIndex.from_tuples(
            [(d, "SH600519") for d in dates_ret],
            names=["datetime", "instrument"],
        )
        returns_df = pd.DataFrame({"return_5d": np.random.randn(100)}, index=ret_idx)
        result = validate_data_consistency(factor_results, returns_df)
        assert result is False

    def test_empty_factor_results(self) -> None:
        returns_df = pd.DataFrame({"return_5d": [1.0]}, index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-01"), "SH600519")], names=["datetime", "instrument"]
        ))
        result = validate_data_consistency({}, returns_df)
        assert result is False

    def test_nan_factor_values_ignored(self) -> None:
        """dropna 后仍有足够样本 → True。"""
        dates = pd.date_range("2026-01-01", periods=200, freq="D")
        idx = pd.MultiIndex.from_tuples([(d, "SH600519") for d in dates], names=["datetime", "instrument"])
        vals = np.ones(200)
        vals[:10] = np.nan  # 前10个 NaN
        factor_results = {"mom5": pd.Series(vals, index=idx)}
        returns_df = pd.DataFrame({"return_5d": np.random.randn(200)}, index=idx)
        result = validate_data_consistency(factor_results, returns_df)
        assert result is True
