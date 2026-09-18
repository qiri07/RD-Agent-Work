"""RD-Agent-Work: engine/ic_scan.py 和 engine/recompute.py 向后兼容入口测试（修正版）。"""

from __future__ import annotations

import pytest


class TestIcScanImport:
    """engine/ic_scan.py 模块导入测试。"""

    def test_import_compute_ic(self) -> None:
        from engine.ic_scan import compute_ic
        assert callable(compute_ic)

    def test_import_ic_analysis(self) -> None:
        from engine.ic_scan import ic_analysis
        assert callable(ic_analysis)

    def test_import_run_ic_scan(self) -> None:
        from engine.ic_scan import run_ic_scan
        assert callable(run_ic_scan)

    def test_import_constants(self) -> None:
        from engine.ic_scan import IC_FORWARD_DAYS, IC_WINSORIZE, IC_MIN_STOCKS_PER_DAY
        assert isinstance(IC_FORWARD_DAYS, list)
        assert isinstance(IC_WINSORIZE, float)
        assert isinstance(IC_MIN_STOCKS_PER_DAY, int)

    def test_import_load_returns_from_sessions(self) -> None:
        from engine.ic_scan import load_returns_from_sessions
        assert callable(load_returns_from_sessions)

    def test_import_validate_data_consistency(self) -> None:
        from engine.ic_scan import validate_data_consistency
        assert callable(validate_data_consistency)

    def test_all_exported_names(self) -> None:
        from engine import ic_scan
        expected = {
            "compute_ic", "ic_analysis", "load_returns_from_sessions",
            "validate_data_consistency", "run_ic_scan",
            "IC_FORWARD_DAYS", "IC_WINSORIZE", "IC_MIN_STOCKS_PER_DAY",
            "logger",
        }
        assert set(ic_scan.__all__) == expected


class TestRecomputeImport:
    """engine/recompute.py 模块导入测试。"""

    def test_import_run_phase1_recompute(self) -> None:
        from engine.recompute import run_phase1_recompute
        assert callable(run_phase1_recompute)

    def test_import_run_phase2_ic_analysis(self) -> None:
        from engine.recompute import run_phase2_ic_analysis
        assert callable(run_phase2_ic_analysis)

    def test_import_ic_analysis_yearly(self) -> None:
        from engine.recompute import ic_analysis_yearly
        assert callable(ic_analysis_yearly)

    def test_import_generate_ic_report(self) -> None:
        from engine.recompute import generate_ic_report
        assert callable(generate_ic_report)

    def test_import_print_summary(self) -> None:
        from engine.recompute import print_summary
        assert callable(print_summary)

    def test_import_run_full_recompute(self) -> None:
        from engine.recompute import run_full_recompute
        assert callable(run_full_recompute)

    def test_import_load_functions(self) -> None:
        from engine.recompute import load_factor_results, load_returns
        assert callable(load_factor_results)
        assert callable(load_returns)

    def test_backward_compat_aliases(self) -> None:
        """模块级 _load_factor_results / _load_returns 别名可用。"""
        from engine.recompute import _load_factor_results, _load_returns
        assert callable(_load_factor_results)
        assert callable(_load_returns)

    def test_all_exported_names(self) -> None:
        from engine import recompute
        expected = {
            "run_phase1_recompute", "run_phase2_ic_analysis",
            "ic_analysis_yearly", "generate_ic_report",
            "print_summary", "run_full_recompute",
            "load_factor_results", "load_returns",
            "_load_factor_results", "_load_returns",
        }
        assert set(recompute.__all__) == expected
