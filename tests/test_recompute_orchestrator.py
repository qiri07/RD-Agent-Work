"""engine/recompute/orchestrator.py 全覆盖测试（修正版）。

patch 目标改为 batch_recompute_factors 模块（实际定义位置）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.recompute.orchestrator import run_phase1_recompute, run_phase2_ic_analysis


def _make_sessions(tmp_path: Path, n: int = 2) -> list[Path]:
    sessions = []
    for i in range(n):
        sd = tmp_path / f"session_{i}"
        sd.mkdir(parents=True, exist_ok=True)
        sessions.append(sd)
    return sessions


class TestRunPhase1Recompute:
    def test_all_success(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, n=2)
        with patch("batch_recompute_factors.get_sessions", return_value=sessions):
            with patch("batch_recompute_factors.copy_data_to_session", return_value=True):
                with patch("batch_recompute_factors.recompute_factor", return_value=(True, "ok")):
                    success, fail = run_phase1_recompute()
        assert len(success) == 2
        assert len(fail) == 0

    def test_some_failures(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, n=3)
        call_idx = [0]
        def mock_recompute(s):
            call_idx[0] += 1
            return (False, "error") if call_idx[0] == 2 else (True, "ok")
        with patch("batch_recompute_factors.get_sessions", return_value=sessions):
            with patch("batch_recompute_factors.copy_data_to_session", return_value=True):
                with patch("batch_recompute_factors.recompute_factor", side_effect=mock_recompute):
                    success, fail = run_phase1_recompute()
        assert len(success) == 2
        assert len(fail) == 1

    def test_copy_data_fails(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, n=1)
        with patch("batch_recompute_factors.get_sessions", return_value=sessions):
            with patch("batch_recompute_factors.copy_data_to_session", return_value=False):
                success, fail = run_phase1_recompute()
        assert len(success) == 0
        assert len(fail) == 0

    def test_no_sessions(self) -> None:
        with patch("batch_recompute_factors.get_sessions", return_value=[]):
            success, fail = run_phase1_recompute()
        assert success == []
        assert fail == []


class TestRunPhase2IcAnalysis:
    def test_no_factor_results_returns_none(self) -> None:
        with patch("engine.recompute.orchestrator.load_factor_results", return_value={}):
            result = run_phase2_ic_analysis()
        assert result is None

    def test_empty_ic_df_returns_none(self, tmp_path: Path) -> None:
        mock_factor_results = {"mom5": pd.Series([1.0])}
        mock_returns = pd.DataFrame({"return_5d": [1.0]})
        with patch("engine.recompute.orchestrator.load_factor_results", return_value=mock_factor_results):
            with patch("engine.recompute.orchestrator.load_returns", return_value=mock_returns):
                with patch("engine.ic_scan.ic_analysis", return_value=pd.DataFrame()):
                    result = run_phase2_ic_analysis()
        assert result is None

    def test_ic_analysis_returns_none(self, tmp_path: Path) -> None:
        mock_factor_results = {"mom5": pd.Series([1.0])}
        mock_returns = pd.DataFrame({"return_5d": [1.0]})
        with patch("engine.recompute.orchestrator.load_factor_results", return_value=mock_factor_results):
            with patch("engine.recompute.orchestrator.load_returns", return_value=mock_returns):
                with patch("engine.ic_scan.ic_analysis", return_value=None):
                    result = run_phase2_ic_analysis()
        assert result is None
