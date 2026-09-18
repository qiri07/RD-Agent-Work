"""engine/recompute/loader.py 全覆盖测试。

覆盖：
  - load_factor_results h5 / parquet 两种格式
  - load_factor_results 跳过异常
  - load_returns session 路径 + fallback 路径
  - load_returns 空 session 降级
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_factor_h5(ws: Path, name: str, n_dates: int = 10) -> Path:
    session_dir = ws / name
    session_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2026-01-01", periods=n_dates, freq="D")
    df = pd.DataFrame({
        "factor_val": np.random.randn(n_dates).tolist(),
    })
    df.index = pd.MultiIndex.from_tuples(
        [(d, "SH600519") for d in dates],
        names=["datetime", "instrument"],
    )
    h5_path = session_dir / "result.h5"
    df.to_hdf(h5_path, key="data")
    return h5_path


def _make_factor_pq(ws: Path, name: str, n_dates: int = 10) -> Path:
    session_dir = ws / name
    session_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2026-01-01", periods=n_dates, freq="D")
    df = pd.DataFrame({
        "factor_val": np.random.randn(n_dates).tolist(),
    })
    df.index = pd.MultiIndex.from_tuples(
        [(d, "SH600519") for d in dates],
        names=["datetime", "instrument"],
    )
    pq_path = session_dir / "result.parquet"
    df.to_parquet(pq_path)
    return pq_path


def _make_session_pq(ws: Path, name: str, n_dates: int = 20) -> Path:
    session_dir = ws / name
    session_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2026-01-01", periods=n_dates, freq="D")
    df = pd.DataFrame({
        "date": dates,
        "instrument": ["SH600519"] * n_dates,
        "$close": [100.0 + i * 0.1 for i in range(n_dates)],
        "$open": [100.0 + i * 0.1 for i in range(n_dates)],
        "$high": [101.0 + i * 0.1 for i in range(n_dates)],
        "$low": [99.0 + i * 0.1 for i in range(n_dates)],
        "$volume": [1e6] * n_dates,
    })
    df = df.set_index(["date", "instrument"]).sort_index()
    pq_path = session_dir / "daily_pv.parquet"
    df.to_parquet(pq_path)
    return pq_path


# ── load_factor_results ──────────────────────────────────────────────────────


class TestLoadFactorResults:
    def test_loads_h5_factors(self, tmp_path: Path) -> None:
        import engine.recompute.loader as mod
        from unittest.mock import patch
        mock_cfg = MagicMock()
        ws = tmp_path / "workspace"
        ws.mkdir()
        _make_factor_h5(ws, "momentum_5d")
        _make_factor_h5(ws, "momentum_10d")
        mock_cfg.RDAGENT_WORKSPACE = ws
        with patch.object(mod, "cfg", mock_cfg):
            result = mod.load_factor_results()
        assert len(result) == 2
        assert "momentum_5d" in result
        assert "momentum_10d" in result

    def test_loads_parquet_factors(self, tmp_path: Path) -> None:
        import engine.recompute.loader as mod
        from unittest.mock import patch
        mock_cfg = MagicMock()
        ws = tmp_path / "workspace"
        ws.mkdir()
        _make_factor_pq(ws, "reversal_5d")
        mock_cfg.RDAGENT_WORKSPACE = ws
        with patch.object(mod, "cfg", mock_cfg):
            result = mod.load_factor_results()
        assert len(result) == 1
        assert "reversal_5d" in result

    def test_h5_takes_precedence_over_parquet(self, tmp_path: Path) -> None:
        """h5 和 parquet 同时存在时，优先读取 h5。"""
        import engine.recompute.loader as mod
        from unittest.mock import patch
        mock_cfg = MagicMock()
        ws = tmp_path / "workspace"
        ws.mkdir()
        _make_factor_h5(ws, "both")
        _make_factor_pq(ws, "both")
        mock_cfg.RDAGENT_WORKSPACE = ws
        with patch.object(mod, "cfg", mock_cfg):
            result = mod.load_factor_results()
        assert len(result) == 1
        assert "both" in result

    def test_skips_non_dir_entries(self, tmp_path: Path) -> None:
        import engine.recompute.loader as mod
        from unittest.mock import patch
        mock_cfg = MagicMock()
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "not_a_dir.txt").write_text("ignore")
        mock_cfg.RDAGENT_WORKSPACE = ws
        with patch.object(mod, "cfg", mock_cfg):
            result = mod.load_factor_results()
        assert result == {}

    def test_skips_broken_h5(self, tmp_path: Path) -> None:
        import engine.recompute.loader as mod
        from unittest.mock import patch
        mock_cfg = MagicMock()
        ws = tmp_path / "workspace"
        ws.mkdir()
        session_dir = ws / "broken"
        session_dir.mkdir()
        (session_dir / "result.h5").write_text("not hdf5", encoding="utf-8")
        mock_cfg.RDAGENT_WORKSPACE = ws
        with patch.object(mod, "cfg", mock_cfg):
            result = mod.load_factor_results()
        assert result == {}


# ── load_returns ─────────────────────────────────────────────────────────────


class TestLoadReturns:
    def test_loads_from_sessions(self, tmp_path: Path) -> None:
        import engine.recompute.loader as mod
        from unittest.mock import patch
        mock_cfg = MagicMock()
        ws = tmp_path / "workspace"
        ws.mkdir()
        _make_session_pq(ws, "session1")
        _make_session_pq(ws, "session2")
        mock_cfg.RDAGENT_WORKSPACE = ws

        with patch.object(mod, "cfg", mock_cfg):
            with patch("batch_recompute_factors.get_sessions", return_value=[
                ws / "session1", ws / "session2"
            ]):
                result = mod.load_returns()
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        assert "return_1d" in result.columns

    def test_fallback_to_source_pq(self, tmp_path: Path) -> None:
        """无 session 数据时，降级到 DAILY_PV_PQ / DAILY_PV_FULL_PQ。"""
        import engine.recompute.loader as mod
        from unittest.mock import patch
        mock_cfg = MagicMock()
        ws = tmp_path / "workspace"
        ws.mkdir()
        # 创建 DAILY_PV_FULL_PQ
        dates = pd.date_range("2026-01-01", periods=30, freq="D")
        df = pd.DataFrame({
            "date": dates,
            "instrument": ["SH600519"] * 30,
            "$close": [100.0 + i * 0.1 for i in range(30)],
        })
        df = df.set_index(["date", "instrument"]).sort_index()
        full_pq = tmp_path / "daily_pv_full.parquet"
        df.to_parquet(full_pq)
        mock_cfg.RDAGENT_WORKSPACE = ws
        mock_cfg.DAILY_PV_PQ = tmp_path / "missing.parquet"
        mock_cfg.DAILY_PV_FULL_PQ = full_pq

        with patch.object(mod, "cfg", mock_cfg):
            with patch("batch_recompute_factors.get_sessions", return_value=[]):
                result = mod.load_returns()
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        assert "return" in result.columns

    def test_empty_sessions_and_no_source(self, tmp_path: Path) -> None:
        """无 session 且无 source → 抛异常或返回空。"""
        import engine.recompute.loader as mod
        from unittest.mock import patch
        mock_cfg = MagicMock()
        ws = tmp_path / "workspace"
        ws.mkdir()
        mock_cfg.RDAGENT_WORKSPACE = ws
        mock_cfg.DAILY_PV_PQ = tmp_path / "no_pq.parquet"
        mock_cfg.DAILY_PV_FULL_PQ = tmp_path / "no_full.parquet"

        with patch.object(mod, "cfg", mock_cfg):
            with patch("batch_recompute_factors.get_sessions", return_value=[]):
                with pytest.raises((FileNotFoundError, pd.errors.EmptyDataError)):
                    mod.load_returns()

    def test_session_read_error_skipped(self, tmp_path: Path) -> None:
        """session parquet 读取失败时跳过。"""
        import engine.recompute.loader as mod
        from unittest.mock import patch
        mock_cfg = MagicMock()
        ws = tmp_path / "workspace"
        ws.mkdir()
        bad_session = ws / "bad_session"
        bad_session.mkdir()
        (bad_session / "daily_pv.parquet").write_text("not parquet", encoding="utf-8")
        good_session = ws / "good_session"
        good_session.mkdir()
        _make_session_pq(ws, "good_session")
        mock_cfg.RDAGENT_WORKSPACE = ws

        with patch.object(mod, "cfg", mock_cfg):
            with patch("batch_recompute_factors.get_sessions", return_value=[bad_session, good_session]):
                result = mod.load_returns()
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
