"""stock_analyzer/report.py 全覆盖测试。

覆盖：
  - generate_report 生成 JSON 报告
  - save_cross_sectional_ic 保存 IC CSV
  - save_ranking 保存排名 CSV
  - 各分支路径（空结果、异常跳过）
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_stock_df(dates: list[str], prices: list[float]) -> pd.DataFrame:
    instruments = ["SH600519"] * len(dates)
    data = {
        "date": pd.to_datetime(dates),
        "instrument": instruments,
        "$open": prices,
        "$close": prices,
        "$high": [p * 1.01 for p in prices],
        "$low": [p * 0.99 for p in prices],
        "$volume": [1e6] * len(dates),
    }
    return pd.DataFrame(data).set_index(["date", "instrument"]).sort_index()


def _make_factor_df(dates: list[str], values: list[float]) -> pd.DataFrame:
    instruments = ["SH600519"] * len(dates)
    data = {
        "date": pd.to_datetime(dates),
        "instrument": instruments,
        "momentum_5d": values,
        "rsi_14": [50.0] * len(dates),
    }
    return pd.DataFrame(data).set_index(["date", "instrument"]).sort_index()


# ── generate_report ──────────────────────────────────────────────────────────


class TestGenerateReport:
    def test_generates_json_file(self, tmp_path: Path) -> None:
        from stock_analyzer.report import generate_report

        dates = ["2026-07-" + str(i).zfill(2) for i in range(1, 31)]
        prices = [100.0 + i for i in range(30)]
        stock_df = _make_stock_df(dates, prices)
        factor_df = _make_factor_df(dates, [0.02] * 30)

        close = stock_df["$close"]
        daily_ret = close.pct_change().dropna()
        ann_ret = (1 + daily_ret).prod() ** (252 / len(daily_ret)) - 1
        ann_vol = daily_ret.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cumret = (1 + daily_ret).cumprod()
        max_dd = (cumret / cumret.cummax() - 1).min()
        stats = {"ann_ret": ann_ret, "ann_vol": ann_vol, "sharpe": sharpe, "max_dd": max_dd}
        (tmp_path / "output").mkdir(exist_ok=True)

        report = generate_report(
            ticker="SH600519",
            display_name="贵州茅台",
            src_pq=tmp_path / "src.parquet",
            dates=stock_df.index.get_level_values(0),
            n_days=len(dates),
            close=close,
            stats=stats,
            yearly_stats=[],
            backtest_results=[],
            ic_records=[],
            factor_df=factor_df,
            out_dir=tmp_path / "output",
        )

        assert isinstance(report, dict)
        assert report["ticker"] == "SH600519"
        assert report["target"] == "贵州茅台"
        assert report["factor_count"] == 2
        assert "timestamp" in report

        # 文件写入验证
        expected_file = tmp_path / "output" / "sh600519_report.json"
        assert expected_file.exists()
        import json
        with open(expected_file, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["ticker"] == "SH600519"

    def test_report_with_yearly_stats(self, tmp_path: Path) -> None:
        from stock_analyzer.report import generate_report

        dates = ["2025-07-01", "2026-07-01"]
        prices = [100.0, 110.0]
        stock_df = _make_stock_df(dates, prices)
        factor_df = _make_factor_df(dates, [0.02, 0.03])
        close = stock_df["$close"]
        daily_ret = close.pct_change().dropna()
        stats = {"ann_ret": 0.1, "ann_vol": 0.2, "sharpe": 0.5, "max_dd": -0.05}
        yearly_stats = [{"year": 2026, "return_pct": 10.0, "volatility_pct": 15.0}]
        (tmp_path / "out2").mkdir(exist_ok=True)

        report = generate_report(
            ticker="SH600519", display_name="茅台", src_pq=tmp_path / "src.parquet",
            dates=stock_df.index.get_level_values(0), n_days=2,
            close=close, stats=stats, yearly_stats=yearly_stats,
            backtest_results=[], ic_records=[], factor_df=factor_df,
            out_dir=tmp_path / "out2",
        )
        assert report["yearly_performance"] == yearly_stats


# ── save_cross_sectional_ic ──────────────────────────────────────────────────


class TestSaveCrossSectionalIc:
    def test_saves_ic_csv(self, tmp_path: Path) -> None:
        from stock_analyzer.report import save_cross_sectional_ic

        # 构建 workspace 目录结构
        ws = tmp_path / "workspace"
        ws.mkdir()
        session_dir = ws / "momentum_5d"
        session_dir.mkdir()
        # 创建 result.h5
        dates = ["2026-07-01", "2026-07-02"]
        df = pd.DataFrame({
            "date": pd.to_datetime(dates),
            "instrument": ["SH600519", "SH600519"],
            "momentum_5d": [0.02, 0.03],
        }).set_index(["date", "instrument"])
        df.to_hdf(session_dir / "result.h5", key="data")

        out_dir = tmp_path / "ic_out"
        out_dir.mkdir(exist_ok=True)
        n = save_cross_sectional_ic("SH600519", ws, out_dir)
        assert n == 1
        ic_csv = out_dir / "sh600519_ic.csv"
        assert ic_csv.exists()
        ic_df = pd.read_csv(ic_csv)
        assert len(ic_df) == 1
        assert ic_df.iloc[0]["factor_id"] == "momentum_5d"

    def test_no_h5_files_returns_zero(self, tmp_path: Path) -> None:
        from stock_analyzer.report import save_cross_sectional_ic
        ws = tmp_path / "empty_ws"
        ws.mkdir()
        out_dir = tmp_path / "ic_out2"
        out_dir.mkdir(exist_ok=True)
        n = save_cross_sectional_ic("SH600519", ws, out_dir)
        assert n == 0
        assert not (out_dir / "sh600519_ic.csv").exists()

    def test_h5_read_error_skipped(self, tmp_path: Path) -> None:
        from stock_analyzer.report import save_cross_sectional_ic
        ws = tmp_path / "bad_ws"
        ws.mkdir()
        session_dir = ws / "broken"
        session_dir.mkdir()
        (session_dir / "result.h5").write_text("not hdf5", encoding="utf-8")
        out_dir = tmp_path / "ic_out3"
        out_dir.mkdir(exist_ok=True)
        n = save_cross_sectional_ic("SH600519", ws, out_dir)
        assert n == 0


# ── save_ranking ─────────────────────────────────────────────────────────────


class TestSaveRanking:
    def test_saves_ranking_csv(self, tmp_path: Path) -> None:
        from stock_analyzer.report import save_ranking

        ws = tmp_path / "workspace"
        ws.mkdir()
        session_dir = ws / "mom5"
        session_dir.mkdir()
        dates = pd.date_range("2026-07-01", periods=50, freq="D")
        # 50只股票 × 50天，确保每只股票每天有数据
        instruments = [f"SH{i:06d}" for i in range(1, 51)]
        np.random.seed(42)
        rows = []
        for d in dates:
            for inst in instruments:
                rows.append({"date": d, "instrument": inst, "momentum_5d": float(np.random.randn())})
        df = pd.DataFrame(rows).set_index(["date", "instrument"])
        # 确保目标股票 SH000001 在所有日期都有非 NaN 值
        target = "SH000001"
        for d in dates:
            df.loc[(d, target), "momentum_5d"] = 0.05
        df.to_hdf(session_dir / "result.h5", key="data")

        # 再加第二个因子
        session_dir2 = ws / "mom10"
        session_dir2.mkdir()
        df2 = df.copy()
        df2["momentum_10d"] = [float(np.random.randn()) for _ in range(len(df2))]
        df2.to_hdf(session_dir2 / "result.h5", key="data")

        stock_df = _make_stock_df(
            [d.strftime("%Y-%m-%d") for d in dates],
            [100.0 + i for i in range(50)],
        )
        out_dir = tmp_path / "rank_out"
        out_dir.mkdir(exist_ok=True)
        save_ranking(target, stock_df.index.get_level_values(0), ws, out_dir)
        ranking_csv = out_dir / f"{target.lower()}_ranking.csv"
        assert ranking_csv.exists()
        rd = pd.read_csv(ranking_csv)
        assert len(rd) > 0
        assert "date" in rd.columns

    def test_no_h5_files_no_output(self, tmp_path: Path) -> None:
        from stock_analyzer.report import save_ranking
        ws = tmp_path / "empty"
        ws.mkdir()
        stock_df = _make_stock_df(["2026-07-01"], [100.0])
        out_dir = tmp_path / "rank_out2"
        out_dir.mkdir(exist_ok=True)
        save_ranking("SH600519", stock_df.index.get_level_values(0), ws, out_dir)
        assert not (out_dir / "sh600519_ranking.csv").exists()
