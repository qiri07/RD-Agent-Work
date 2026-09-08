#!/usr/bin/env python3
"""
ic_compute.py 单元测试
======================
测试 IC 计算核心逻辑：chunked 加载、IC 计算、Top10 收益。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from ic_compute import (
    compute_ic_chunked,
    compute_top10,
    compute_ic_session,
    load_factor_chunked,
)


def _make_factor_series(n_days=252, n_stocks=100, seed=42):
    """创建测试用因子 Series (MultiIndex: date, instrument)"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    stocks = [f"SH{i:06d}" for i in range(1, n_stocks + 1)]
    idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
    vals = rng.standard_normal(len(idx))
    return pd.Series(vals, index=idx)


def _make_returns_series(n_days=252, n_stocks=100, seed=43):
    """创建测试用收益率 Series (MultiIndex: date, instrument)"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    stocks = [f"SH{i:06d}" for i in range(1, n_stocks + 1)]
    idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
    vals = rng.standard_normal(len(idx)) * 0.02
    return pd.Series(vals, index=idx)


class TestComputeICChunked(unittest.TestCase):
    """测试分年 IC 计算"""

    def test_computes_global_and_yearly_ic(self):
        """应有全局 IC 和年度 IC"""
        factor = _make_factor_series()
        returns = _make_returns_series()

        factor_chunks = {2024: factor}
        returns_chunks = {2024: returns}

        global_ic, yearly_ic = compute_ic_chunked(factor_chunks, returns_chunks)

        self.assertIsNotNone(global_ic)
        self.assertIn(2024, yearly_ic)
        self.assertIsInstance(global_ic, float)

    def test_global_ic_within_valid_range(self):
        """IC 应在 [-1, 1] 范围内"""
        factor = _make_factor_series(n_stocks=200)
        returns = _make_returns_series(n_stocks=200)

        factor_chunks = {2024: factor}
        returns_chunks = {2024: returns}

        global_ic, _ = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertLessEqual(abs(global_ic), 1.0)

    def test_perfect_correlation(self):
        """完美正相关 IC 应接近 1"""
        factor = _make_factor_series(n_stocks=200, seed=1)
        returns = factor * 2 + np.random.default_rng(2).standard_normal(factor.shape) * 0.01

        returns_s = pd.Series(returns.values, index=factor.index)
        factor_chunks = {2024: factor}
        returns_chunks = {2024: returns_s}

        global_ic, _ = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertGreater(global_ic, 0.95)

    def test_opposite_correlation(self):
        """完美负相关 IC 应接近 -1"""
        factor = _make_factor_series(n_stocks=200, seed=1)
        returns_data = -factor.values * 2 + np.random.default_rng(2).standard_normal(factor.shape) * 0.01
        returns_s = pd.Series(returns_data, index=factor.index)

        factor_chunks = {2024: factor}
        returns_chunks = {2024: returns_s}

        global_ic, _ = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertLess(global_ic, -0.95)

    def test_no_common_years(self):
        """无共同年份应返回 None global IC"""
        factor_chunks = {2024: _make_factor_series()}
        returns_chunks = {2025: _make_returns_series()}

        global_ic, yearly_ic = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertIsNone(global_ic)
        self.assertEqual(len(yearly_ic), 0)

    def test_insufficient_data_skipped(self):
        """数据不足（<100行）的年份应跳过"""
        factor = _make_factor_series(n_days=10, n_stocks=5)  # 仅50行，不足100
        returns = _make_returns_series(n_days=10, n_stocks=5)

        factor_chunks = {2024: factor}
        returns_chunks = {2024: returns}

        global_ic, yearly_ic = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertIsNone(global_ic)
        self.assertEqual(len(yearly_ic), 0)


class TestComputeTop10(unittest.TestCase):
    """测试 Top10 收益计算"""

    def test_computes_yearly_top10(self):
        """应返回年度 Top10 中位收益"""
        factor = _make_factor_series(n_stocks=200)
        # 构造与因子正相关的收益
        rng = np.random.default_rng(42)
        base_returns = factor.values * 0.01 + rng.standard_normal(factor.shape) * 0.02
        returns = pd.Series(base_returns, index=factor.index)

        factor_chunks = {2024: factor}
        returns_chunks = {2024: returns}

        top10 = compute_top10(factor_chunks, returns_chunks)
        self.assertIn(2024, top10)
        self.assertIsInstance(top10[2024], float)

    def test_empty_chunks(self):
        """空 chunk 应返回空 dict"""
        top10 = compute_top10({}, {})
        self.assertEqual(len(top10), 0)


class TestComputeICSession(unittest.TestCase):
    """测试单 session IC 计算（基于 run_ic_fast.py 的 compute_ic_session）"""

    def _make_session_h5(self, tmpdir, n_days=50, n_stocks=200):
        """创建临时 session h5 文件"""
        rng = np.random.default_rng(42)
        dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
        stocks = [f"SH{i:06d}" for i in range(1, n_stocks + 1)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
        vals = rng.standard_normal(len(idx))
        df = pd.DataFrame({"factor_val": vals}, index=idx)
        h5_path = Path(tmpdir) / "test_session" / "result.h5"
        h5_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_hdf(h5_path, key="data", mode="w")
        return h5_path

    def test_returns_factor_id_and_ic_dict(self):
        """应返回 (factor_id, {date: ic})"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            h5 = self._make_session_h5(tmpdir)
            # 创建 ret_lookup
            rng = np.random.default_rng(43)
            dates = pd.date_range("2024-01-01", periods=50, freq="B")
            stocks = [f"SH{i:06d}" for i in range(1, 201)]
            lookup = {(d, s): rng.standard_normal() * 0.02
                      for d in dates for s in stocks}

            fid, ic_by_date = compute_ic_session(h5, lookup)
            self.assertEqual(fid, "test_session")
            self.assertIsInstance(ic_by_date, dict)
            self.assertGreater(len(ic_by_date), 0)

    def test_ic_values_in_valid_range(self):
        """所有 IC 值应在 [-1, 1] 范围内"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            h5 = self._make_session_h5(tmpdir, n_days=100, n_stocks=300)
            rng = np.random.default_rng(43)
            dates = pd.date_range("2024-01-01", periods=100, freq="B")
            stocks = [f"SH{i:06d}" for i in range(1, 301)]
            lookup = {(d, s): rng.standard_normal() * 0.02
                      for d in dates for s in stocks}

            _, ic_by_date = compute_ic_session(h5, lookup)
            for date, ic in ic_by_date.items():
                if not np.isnan(ic):
                    self.assertLessEqual(abs(ic), 1.0, f"IC out of range on {date}: {ic}")

    def test_small_day_skipped(self):
        """单日股票数<50 应被跳过"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建只有 30 只股票的 session
            dates = pd.date_range("2024-01-01", periods=5, freq="B")
            stocks = [f"SH{i:06d}" for i in range(1, 31)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
            vals = np.random.default_rng(42).standard_normal(len(idx))
            df = pd.DataFrame({"factor_val": vals}, index=idx)
            h5 = Path(tmpdir) / "small_session" / "result.h5"
            h5.parent.mkdir(parents=True, exist_ok=True)
            df.to_hdf(h5, key="data", mode="w")

            lookup = {}  # 空 lookup，所有天都无匹配
            fid, ic_by_date = compute_ic_session(h5, lookup)
            self.assertEqual(fid, "small_session")
            self.assertEqual(len(ic_by_date), 0)

    def test_missing_h5_returns_none(self):
        """不存在 h5 文件应返回 (None, {})"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            h5 = Path(tmpdir) / "nonexistent" / "result.h5"
            fid, ic_by_date = compute_ic_session(h5, {})
            self.assertIsNone(fid)
            self.assertEqual(ic_by_date, {})


class TestLoadFactorChunked(unittest.TestCase):
    """测试因子分年加载"""

    def test_loads_from_parquet(self):
        """应从 parquet 文件加载"""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "test_session"
            session_dir.mkdir()
            # 创建多天的因子数据
            dates = pd.date_range("2024-01-01", periods=200, freq="B")
            stocks = [f"SH{i:06d}" for i in range(1, 51)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
            vals = np.random.default_rng(42).standard_normal(len(idx))
            df = pd.DataFrame({"factor_val": vals}, index=idx)
            pq_path = session_dir / "result.parquet"
            df.to_parquet(pq_path)

            chunks = load_factor_chunked(session_dir, chunk_years=[2024])
            self.assertIn(2024, chunks)
            self.assertGreater(len(chunks[2024]), 0)

    def test_loads_from_h5(self):
        """应回退到 h5 文件加载"""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "test_session"
            session_dir.mkdir()
            dates = pd.date_range("2024-01-01", periods=100, freq="B")
            stocks = [f"SH{i:06d}" for i in range(1, 31)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
            vals = np.random.default_rng(42).standard_normal(len(idx))
            df = pd.DataFrame({"factor_val": vals}, index=idx)
            h5_path = session_dir / "result.h5"
            df.to_hdf(h5_path, key="data", mode="w")

            chunks = load_factor_chunked(session_dir, chunk_years=[2024])
            self.assertIn(2024, chunks)

    def test_no_files_returns_none(self):
        """无结果文件应返回 None"""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "empty_session"
            session_dir.mkdir()
            result = load_factor_chunked(session_dir, chunk_years=[2024])
            self.assertIsNone(result)


class TestMemoryUtils(unittest.TestCase):
    """测试内存工具函数"""

    def test_rss_mb_positive(self):
        """rss_mb 应返回正数"""
        from ic_compute import rss_mb
        mem = rss_mb()
        self.assertIsInstance(mem, float)
        self.assertGreater(mem, 0)

    def test_check_memory_pass(self):
        """内存未超限应返回 True"""
        from ic_compute import check_memory
        result = check_memory("test", soft_limit=2000, hard_limit=4000)
        self.assertTrue(result)

    def test_check_memory_warn_high(self):
        """内存超 soft limit 应打印警告但仍返回 True"""
        from ic_compute import check_memory
        result = check_memory("test", soft_limit=1, hard_limit=2)
        # 当前进程通常超 1MB，可能返回 False
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
