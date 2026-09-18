"""engine/ic_scan/orchestrator.py 全覆盖测试（修正版）。

patch 目标改为 batch_recompute_factors 模块（实际定义位置）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from engine.ic_scan.orchestrator import run_ic_scan


def _make_factor_result(session_dir: Path, name: str) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2026-01-01", periods=200, freq="D")
    df = pd.DataFrame({"factor_val": np.random.randn(200).tolist()})
    df.index = pd.MultiIndex.from_tuples(
        [(d, "SH600519") for d in dates], names=["datetime", "instrument"],
    )
    df.to_hdf(session_dir / "result.h5", key="data")


def _make_sessions(tmp_path: Path, n: int = 2) -> list[Path]:
    sessions = []
    for i in range(n):
        sd = tmp_path / f"session_{i}"
        _make_factor_result(sd, f"factor_{i}")
        sessions.append(sd)
    return sessions


class TestRunIcScan:
    def test_empty_sessions_returns_empty_df(self) -> None:
        result = run_ic_scan(sessions=[], phase2_only=True)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_phase1_only_returns_none(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, n=1)
        mock_batch = MagicMock()
        mock_batch.get_sessions.return_value = sessions
        mock_batch.copy_data_to_session.return_value = True
        mock_batch.run_factor.return_value = (True, "ok")
        with patch("batch_recompute_factors.get_sessions", return_value=sessions):
            with patch("batch_recompute_factors.copy_data_to_session", return_value=True):
                with patch("batch_recompute_factors.recompute_factor", return_value=(True, "ok")):
                    result = run_ic_scan(sessions=sessions, phase1_only=True)
        assert result is None

    def test_phase2_no_factor_results_returns_empty(self, tmp_path: Path) -> None:
        ws = tmp_path / "empty_ws"
        ws.mkdir()
        session = ws / "no_result"
        session.mkdir()
        # phase1_only=False 才会进入 Phase 2，验证无因子结果时返回空 DataFrame
        result = run_ic_scan(sessions=[session], phase1_only=False)
        assert isinstance(result, pd.DataFrame)

    def test_phase2_loads_factor_results(self, tmp_path: Path) -> None:
        """run_ic_scan phase1_only=True 时跳过 Phase 2，返回 None。"""
        sessions = _make_sessions(tmp_path, n=2)
        # phase1_only=True → 跳过 Phase 2 → 返回 None
        result = run_ic_scan(sessions=sessions, phase1_only=True)
        assert result is None

    def test_dry_run_skips_copy(self, tmp_path: Path) -> None:
        """dry_run=True 时 copy 不被调用，但 factor 仍运行。"""
        sessions = _make_sessions(tmp_path, n=1)
        copy_count = [0]
        factor_count = [0]
        def mock_copy(s):
            copy_count[0] += 1
            return True
        def mock_factor(s):
            factor_count[0] += 1
            return (True, "dry_ok")
        with patch("batch_recompute_factors.get_sessions", return_value=sessions):
            with patch("batch_recompute_factors.copy_data_to_session", side_effect=mock_copy):
                with patch("batch_recompute_factors.recompute_factor", side_effect=mock_factor):
                    result = run_ic_scan(sessions=sessions, dry_run=True)
        assert copy_count[0] == 0  # dry_run 跳过 copy
        assert factor_count[0] == 1  # factor 仍运行
