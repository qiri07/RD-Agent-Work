"""RD-Agent-Work: engine/data_freshness.py 全覆盖测试（修正版）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest


def _write_pq_with_dates(path: Path, dates: list[str]) -> None:
    rows = []
    for d in dates:
        rows.append({"date": d, "instrument": "SH600519", "$open": 100.0, "$close": 101.0, "$high": 102.0, "$low": 99.0, "$volume": 1e6, "$factor": 1.0})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index(["date", "instrument"])
    df.to_parquet(path)


def _write_factor_h5(workspace: Path, name: str, dates: list[str]) -> None:
    session_dir = workspace / name
    session_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in dates:
        rows.append({"date": d, "instrument": "SH600519", "value": 1.0})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index(["date", "instrument"])
    df.to_hdf(session_dir / "result.h5", key="data")


@pytest.fixture
def fresh_mod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> MagicMock:
    import engine.data_freshness as mod
    cfg_mock = MagicMock()
    cfg_mock.DAILY_PV_FULL_PQ = tmp_path / "daily_pv_full.parquet"
    cfg_mock.RDAGENT_WORKSPACE = tmp_path / "workspace"
    cfg_mock.RDAGENT_WORKSPACE.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "cfg", cfg_mock)
    return cfg_mock


class TestGetPriceDataCutoff:
    def test_file_exists_returns_latest_date(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        pq = tmp_path / "daily_pv_full.parquet"
        _write_pq_with_dates(pq, ["2026-08-01", "2026-08-10", "2026-08-14"])
        mod.cfg.DAILY_PV_FULL_PQ = pq
        result = mod.get_price_data_cutoff()
        assert result is not None
        assert result.date() == pd.Timestamp("2026-08-14").date()

    def test_file_missing_returns_none(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        mod.cfg.DAILY_PV_FULL_PQ = tmp_path / "nonexistent.parquet"
        result = mod.get_price_data_cutoff()
        assert result is None

    def test_read_error_returns_none(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        bad_pq = tmp_path / "bad.parquet"
        bad_pq.write_text("not a parquet", encoding="utf-8")
        mod.cfg.DAILY_PV_FULL_PQ = bad_pq
        result = mod.get_price_data_cutoff()
        assert result is None


class TestGetFactorDataCutoff:
    def test_h5_factors_found(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        _write_factor_h5(ws, "momentum_5d", ["2026-07-01", "2026-08-10"])
        _write_factor_h5(ws, "momentum_10d", ["2026-06-01", "2026-08-12"])
        mod.cfg.RDAGENT_WORKSPACE = ws
        cutoff, count = mod.get_factor_data_cutoff()
        assert cutoff is not None
        assert count == 2
        assert cutoff.date() == pd.Timestamp("2026-08-12").date()

    def test_parquet_factors_found(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        session_dir = ws / "reversal_5d"
        session_dir.mkdir(exist_ok=True)
        rows = [{"date": "2026-08-05", "instrument": "SH600519", "value": 0.5}]
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index(["date", "instrument"])
        df.to_parquet(session_dir / "result.parquet")
        mod.cfg.RDAGENT_WORKSPACE = ws
        cutoff, count = mod.get_factor_data_cutoff()
        assert cutoff is not None
        assert count == 1

    def test_no_factors_returns_none(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        mod.cfg.RDAGENT_WORKSPACE = ws
        cutoff, count = mod.get_factor_data_cutoff()
        assert cutoff is None
        assert count == 0

    def test_session_is_file_skipped(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        (ws / "not_a_dir.txt").write_text("ignore")
        mod.cfg.RDAGENT_WORKSPACE = ws
        cutoff, count = mod.get_factor_data_cutoff()
        assert cutoff is None
        assert count == 0

    def test_h5_read_error_skipped(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        session_dir = ws / "broken"
        session_dir.mkdir(exist_ok=True)
        (session_dir / "result.h5").write_text("not hdf5", encoding="utf-8")
        mod.cfg.RDAGENT_WORKSPACE = ws
        cutoff, count = mod.get_factor_data_cutoff()
        assert cutoff is None
        assert count == 0


class TestCheckDataFreshness:
    def test_both_present_zero_lag(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        pq = tmp_path / "daily_pv_full.parquet"
        _write_pq_with_dates(pq, ["2026-08-14"])
        _write_factor_h5(ws, "mom5", ["2026-08-14"])
        mod.cfg.DAILY_PV_FULL_PQ = pq
        mod.cfg.RDAGENT_WORKSPACE = ws
        result = mod.check_data_freshness()
        assert result["days_lag"] == 0
        assert "正常" in result["freshness"]

    def test_both_present_positive_lag(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        pq = tmp_path / "daily_pv_full.parquet"
        _write_pq_with_dates(pq, ["2026-08-14"])
        _write_factor_h5(ws, "mom5", ["2026-08-10"])
        mod.cfg.DAILY_PV_FULL_PQ = pq
        mod.cfg.RDAGENT_WORKSPACE = ws
        result = mod.check_data_freshness()
        assert result["days_lag"] == 4
        assert "延迟" in result["freshness"]

    def test_price_missing(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        _write_factor_h5(ws, "mom5", ["2026-08-14"])
        mod.cfg.DAILY_PV_FULL_PQ = tmp_path / "missing.parquet"
        mod.cfg.RDAGENT_WORKSPACE = ws
        result = mod.check_data_freshness()
        assert result["price_cutoff"] is None
        assert "价格数据缺失" in result["freshness"]

    def test_factor_missing(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        pq = tmp_path / "daily_pv_full.parquet"
        _write_pq_with_dates(pq, ["2026-08-14"])
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        mod.cfg.DAILY_PV_FULL_PQ = pq
        mod.cfg.RDAGENT_WORKSPACE = ws
        result = mod.check_data_freshness()
        assert result["factor_cutoff"] is None
        assert "因子数据缺失" in result["freshness"]

    def test_both_missing(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """两个数据源都不存在 → freshness='未知'。"""
        import engine.data_freshness as mod
        ws = tmp_path / "no_ws"
        ws.mkdir(exist_ok=True)  # 确保目录存在，避免 iterdir 报错
        mod.cfg.DAILY_PV_FULL_PQ = tmp_path / "no_pq.parquet"
        mod.cfg.RDAGENT_WORKSPACE = ws
        result = mod.check_data_freshness()
        assert result["price_cutoff"] is None
        assert result["factor_cutoff"] is None
        # price_cutoff=None takes precedence → 价格数据缺失
        assert result["freshness"] == "⚠️ 价格数据缺失"

    def test_small_lag_within_3_days(self, fresh_mod: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.data_freshness as mod
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        pq = tmp_path / "daily_pv_full.parquet"
        _write_pq_with_dates(pq, ["2026-08-14"])
        _write_factor_h5(ws, "mom5", ["2026-08-12"])
        mod.cfg.DAILY_PV_FULL_PQ = pq
        mod.cfg.RDAGENT_WORKSPACE = ws
        result = mod.check_data_freshness()
        assert result["days_lag"] == 2
        assert "轻微延迟" in result["freshness"]
