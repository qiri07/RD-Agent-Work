#!/usr/bin/env python3
"""
IC计算详细测试
==============
测试 ic_compute.py 的所有功能，包括边缘情况。
"""
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from ic_compute import (
    load_returns_chunked, load_factor_chunked,
    compute_ic_chunked, compute_top10, compute_ic_session
)


class TestLoadReturnsChunked(unittest.TestCase):
    """测试分年加载returns"""

    def test_loads_parquet(self):
        """从parquet加载"""
        with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as f:
            tmp_path = Path(f.name)
            dates = pd.date_range('2023-01-01', periods=500, freq='B')
            stocks = [f'SH{i:06d}' for i in range(100)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=['date', 'instrument'])
            df = pd.DataFrame({'ret_5d': np.random.rand(50000)}, index=idx)
            df.to_parquet(tmp_path)

        try:
            result = load_returns_chunked(tmp_path, year_start=2023, year_end=2023)
            self.assertIsNotNone(result)
            self.assertIn(2023, result)
        finally:
            tmp_path.unlink()

    def test_loads_hdf(self):
        """从hdf加载"""
        with tempfile.NamedTemporaryFile(suffix='.h5', delete=False) as f:
            tmp_path = Path(f.name)
            dates = pd.date_range('2023-01-01', periods=500, freq='B')
            stocks = [f'SH{i:06d}' for i in range(100)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=['date', 'instrument'])
            df = pd.DataFrame({'ret_5d': np.random.rand(50000)}, index=idx)
            df.to_hdf(tmp_path, key='data', mode='w')

        try:
            result = load_returns_chunked(tmp_path, year_start=2023, year_end=2023)
            self.assertIsNotNone(result)
        finally:
            tmp_path.unlink()

    def test_missing_file(self):
        """文件不存在返回None"""
        result = load_returns_chunked(Path('/nonexistent/path.parquet'))
        self.assertIsNone(result)


class TestLoadFactorChunked(unittest.TestCase):
    """测试分年加载因子"""

    def test_loads_from_h5(self):
        """从h5加载因子"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / 'test_factor'
            session_dir.mkdir()
            
            dates = pd.date_range('2023-01-01', periods=500, freq='B')
            stocks = [f'SH{i:06d}' for i in range(100)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
            df = pd.DataFrame({'value': np.random.rand(50000)}, index=idx)
            df.to_hdf(session_dir / 'result.h5', key='data', mode='w')

            result = load_factor_chunked(session_dir, chunk_years=[2023])
            self.assertIsNotNone(result)
            self.assertIn(2023, result)

    def test_loads_from_parquet(self):
        """从parquet加载因子"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / 'test_factor'
            session_dir.mkdir()
            
            dates = pd.date_range('2023-01-01', periods=500, freq='B')
            stocks = [f'SH{i:06d}' for i in range(100)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
            df = pd.DataFrame({'value': np.random.rand(50000)}, index=idx)
            df.to_parquet(session_dir / 'result.parquet')

            result = load_factor_chunked(session_dir, chunk_years=[2023])
            self.assertIsNotNone(result)

    def test_no_files_returns_none(self):
        """无文件返回None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / 'empty_factor'
            session_dir.mkdir()
            
            result = load_factor_chunked(session_dir)
            self.assertIsNone(result)


class TestComputeICChunked(unittest.TestCase):
    """测试分年IC计算"""

    def test_computes_global_and_yearly_ic(self):
        """计算全局和年度IC"""
        factor_chunks = {
            2023: pd.Series(np.random.rand(1000)),
            2024: pd.Series(np.random.rand(1000)),
        }
        returns_chunks = {
            2023: pd.Series(np.random.rand(1000)),
            2024: pd.Series(np.random.rand(1000)),
        }

        global_ic, yearly_ic = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertIsNotNone(global_ic)
        self.assertIn(2023, yearly_ic)
        self.assertIn(2024, yearly_ic)

    def test_opposite_correlation(self):
        """相反相关性"""
        n = 200
        factor_chunks = {2023: pd.Series(np.arange(n))}
        returns_chunks = {2023: pd.Series(np.arange(n, 0, -1).astype(float))}

        global_ic, _ = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertAlmostEqual(global_ic, -1.0, places=2)

    def test_perfect_correlation(self):
        """完全正相关"""
        n = 200
        factor_chunks = {2023: pd.Series(np.arange(n))}
        returns_chunks = {2023: pd.Series(np.arange(n).astype(float))}

        global_ic, _ = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertAlmostEqual(global_ic, 1.0, places=2)

    def test_insufficient_data_skipped(self):
        """数据不足跳过"""
        factor_chunks = {2023: pd.Series(np.random.rand(50))}  # 少于100
        returns_chunks = {2023: pd.Series(np.random.rand(50))}

        global_ic, yearly_ic = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertIsNone(global_ic)
        self.assertEqual(len(yearly_ic), 0)

    def test_no_common_years(self):
        """无共同年份"""
        factor_chunks = {2023: pd.Series(np.random.rand(200))}
        returns_chunks = {2024: pd.Series(np.random.rand(200))}

        global_ic, yearly_ic = compute_ic_chunked(factor_chunks, returns_chunks)
        self.assertIsNone(global_ic)
        self.assertEqual(len(yearly_ic), 0)


class TestComputeTop10(unittest.TestCase):
    """测试Top10收益计算"""

    def test_computes_yearly_top10(self):
        """计算年度Top10收益"""
        factor_chunks = {2023: pd.Series(np.random.rand(1000))}
        returns_chunks = {2023: pd.Series(np.random.rand(1000))}

        result = compute_top10(factor_chunks, returns_chunks)
        self.assertIn(2023, result)

    def test_empty_chunks(self):
        """空chunks"""
        result = compute_top10({}, {})
        self.assertEqual(result, {})


class TestComputeICSession(unittest.TestCase):
    """测试单session IC计算"""

    def test_returns_factor_id_and_ic_dict(self):
        """返回因子ID和IC字典"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / 'test_session'
            session_dir.mkdir()
            
            dates = pd.date_range('2023-01-01', periods=100, freq='B')
            stocks = [f'SH{i:06d}' for i in range(100)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
            df = pd.DataFrame({'value': np.random.rand(10000)}, index=idx)
            df.to_hdf(session_dir / 'result.h5', key='data', mode='w')

            ret_lookup = {(dates[i], stocks[j]): np.random.rand() for i in range(100) for j in range(100)}
            
            fid, ic_by_date = compute_ic_session(session_dir / 'result.h5', ret_lookup)
            self.assertEqual(fid, 'test_session')
            self.assertEqual(len(ic_by_date), 100)

    def test_missing_h5_returns_none(self):
        """缺失h5文件"""
        ret_lookup = {}
        fid, ic_by_date = compute_ic_session(Path('/nonexistent.h5'), ret_lookup)
        self.assertIsNone(fid)
        self.assertEqual(ic_by_date, {})

    def test_small_day_skipped(self):
        """每日股票数不足跳过"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / 'small_session'
            session_dir.mkdir()
            
            # 只有30只股票
            dates = pd.date_range('2023-01-01', periods=10, freq='B')
            stocks = [f'SH{i:06d}' for i in range(30)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=['datetime', 'instrument'])
            df = pd.DataFrame({'value': np.random.rand(300)}, index=idx)
            df.to_hdf(session_dir / 'result.h5', key='data', mode='w')

            ret_lookup = {}
            fid, ic_by_date = compute_ic_session(session_dir / 'result.h5', ret_lookup)
            # factor_id 应始终返回；ic_by_date 为空因为每天股票数不足50
            self.assertEqual(fid, 'small_session')
            self.assertEqual(ic_by_date, {})


class TestMemoryUtils(unittest.TestCase):
    """测试内存工具"""

    def test_rss_mb_positive(self):
        """RSS为正"""
        from ic_compute import rss_mb
        mem = rss_mb()
        self.assertGreater(mem, 0)

    def test_check_memory_pass(self):
        """内存检查通过"""
        from ic_compute import check_memory
        result = check_memory('test', soft_limit=99999, hard_limit=99999)
        self.assertTrue(result)

    def test_check_memory_warn_high(self):
        """内存超限警告"""
        from ic_compute import check_memory
        result = check_memory('test', soft_limit=1, hard_limit=99999)
        self.assertIsInstance(result, bool)


if __name__ == '__main__':
    unittest.main(verbosity=2)
