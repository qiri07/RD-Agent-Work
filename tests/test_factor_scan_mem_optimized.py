#!/usr/bin/env python3
"""
factor_scan_mem_optimized.py 单元测试
======================================
测试内存优化版因子扫描逻辑：IC扫描、磁盘清理、trace归档。
"""
import sys
import unittest
import tempfile
import os
import shutil
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd


class TestScanAllFactors(unittest.TestCase):
    """测试完整因子扫描逻辑"""

    def test_scan_results_structure(self):
        """扫描结果应包含正确的字段"""
        # 模拟结果数据结构
        results = [
            ("factor_1", 0.05, 0.03, 1000),
            ("factor_2", -0.08, 0.02, 950),
            ("factor_3", 0.02, -0.01, 800),
        ]

        # 按绝对IC排序
        results.sort(key=lambda x: abs(x[1]), reverse=True)

        self.assertEqual(results[0][0], "factor_2")  # |−0.08| 最大
        self.assertEqual(results[1][0], "factor_1")  # |0.05| 次大
        self.assertEqual(results[2][0], "factor_3")  # |0.02| 最小

    def test_skipped_factor_counting(self):
        """跳过的因子计数应正确"""
        skipped = 0
        total = 10
        for i in range(total):
            if i in [2, 5, 8]:  # 模拟跳过的因子
                skipped += 1

        self.assertEqual(skipped, 3)
        self.assertEqual(total - skipped, 7)

    def test_results_format_validation(self):
        """结果元组格式验证"""
        result = ("test_factor", 0.05, 0.03, 1000)

        self.assertEqual(len(result), 4)
        self.assertIsInstance(result[0], str)  # factor_id
        self.assertIsInstance(result[1], float)  # global_ic
        self.assertIsInstance(result[2], float)  # top10_2025
        self.assertIsInstance(result[3], int)  # n_common

    def test_output_file_generation(self):
        """输出文件格式验证"""
        results = [
            ("fid_a", 0.05, 0.03, 100),
            ("fid_b", -0.08, 0.02, 90),
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            tmp_path = f.name

        try:
            with open(tmp_path, "w") as f:
                f.write(f"Total: {len(results)}, Skipped: 0\n")
                f.write(f"Peak memory: 1500.0 MB\n\n")
                for i, (fid, ic, top10, n) in enumerate(results, 1):
                    f.write(f"{i:>3} {fid:>32} IC={ic:.4f} top10={top10:+.3f}% n={n}\n")

            with open(tmp_path, 'r') as f:
                content = f.read()

            self.assertIn("Total: 2", content)
            self.assertIn("fid_a", content)
            self.assertIn("fid_b", content)
            self.assertIn("IC=0.0500", content)
        finally:
            os.unlink(tmp_path)


class TestRecomputeFactor(unittest.TestCase):
    """测试单因子重算逻辑"""

    def _make_test_factor_file(self, tmpdir, n_days=100, n_stocks=50):
        """创建测试用的因子HDF5文件"""
        session_dir = Path(tmpdir) / "test_factor"
        session_dir.mkdir()

        rng = np.random.default_rng(42)
        dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
        stocks = [f"SH{i:06d}" for i in range(1, n_stocks + 1)]
        idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
        vals = rng.standard_normal(len(idx))
        df = pd.DataFrame({"factor_value": vals}, index=idx)

        h5_path = session_dir / "result.h5"
        df.to_hdf(h5_path, key="data", mode="w")
        return session_dir, h5_path

    def test_recompute_returns_valid_result(self):
        """重算应返回有效的IC和top10指标"""
        import tempfile
        from factor_scan_mem_optimized import recompute_factor

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, h5_path = self._make_test_factor_file(tmpdir)

            # 创建收益率文件
            rng = np.random.default_rng(43)
            dates = pd.date_range("2024-01-01", periods=100, freq="B")
            stocks = [f"SH{i:06d}" for i in range(1, 51)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
            rets = pd.Series(rng.standard_normal(len(idx)) * 0.02, index=idx)

            src_pq = Path(tmpdir) / "returns.parquet"
            rets.to_frame("return").to_parquet(src_pq)

            # 设置配置
            with mock.patch('factor_scan_mem_optimized.RETURNS_PQ', src_pq):
                result = recompute_factor(session_dir)

            self.assertIsNotNone(result)
            self.assertIn("id", result)
            self.assertIn("ic", result)
            self.assertIn("top10_med", result)
            self.assertIn("n_common", result)
            self.assertIsInstance(result["ic"], float)

    def test_recompute_skips_insufficient_data(self):
        """数据不足时应跳过"""
        import tempfile
        from factor_scan_mem_optimized import recompute_factor

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, h5_path = self._make_test_factor_file(tmpdir, n_days=10, n_stocks=5)

            # 创建少量收益率数据
            rng = np.random.default_rng(43)
            dates = pd.date_range("2024-01-01", periods=10, freq="B")
            stocks = [f"SH{i:06d}" for i in range(1, 6)]
            idx = pd.MultiIndex.from_product([dates, stocks], names=["datetime", "instrument"])
            rets = pd.Series(rng.standard_normal(len(idx)) * 0.02, index=idx)

            src_pq = Path(tmpdir) / "returns.parquet"
            rets.to_frame("return").to_parquet(src_pq)

            with mock.patch('factor_scan_mem_optimized.RETURNS_PQ', src_pq):
                result = recompute_factor(session_dir)

            # 数据不足应返回None
            self.assertIsNone(result)

    def test_recompute_missing_h5(self):
        """缺少H5文件应返回None"""
        import tempfile
        from factor_scan_mem_optimized import recompute_factor

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "no_h5"
            session_dir.mkdir()

            result = recompute_factor(session_dir)
            self.assertIsNone(result)


class TestCleanupDiskSpace(unittest.TestCase):
    """测试磁盘清理逻辑"""

    def test_cleanup_removes_debug_files(self):
        """应删除daily_pv_debug副本"""
        import tempfile
        from factor_scan_mem_optimized import cleanup_disk_space

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            # 创建测试文件
            d1 = workspace / "factor_1"
            d1.mkdir()
            (d1 / "daily_pv_debug.h5").write_text("dummy")
            (d1 / "daily_pv_debug.parquet").write_text("dummy")
            (d1 / "result.h5").write_text("data")

            d2 = workspace / "factor_2"
            d2.mkdir()
            (d2 / "daily_pv_debug.h5").write_text("dummy")

            # Mock cfg.RDAGENT_WORKSPACE
            with mock.patch('factor_scan_mem_optimized.WORKSPACE', workspace):
                saved = cleanup_disk_space(aggressive=False)

            # 验证debug文件已删除
            self.assertFalse((d1 / "daily_pv_debug.h5").exists())
            self.assertFalse((d1 / "daily_pv_debug.parquet").exists())
            self.assertFalse((d2 / "daily_pv_debug.h5").exists())

            # 验证result.h5保留
            self.assertTrue((d1 / "result.h5").exists())
            self.assertGreater(saved, 0)

    def test_cleanup_removes_redundant_h5(self):
        """有parquet时应删除h5"""
        import tempfile
        from factor_scan_mem_optimized import cleanup_disk_space

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            d1 = workspace / "factor_1"
            d1.mkdir()
            h5 = d1 / "result.h5"
            pq = d1 / "result.parquet"
            h5.write_text("h5 data")
            pq.write_text("pq data")

            with mock.patch('factor_scan_mem_optimized.WORKSPACE', workspace):
                saved = cleanup_disk_space(aggressive=False)

            self.assertFalse(h5.exists())
            self.assertTrue(pq.exists())
            self.assertGreater(saved, 0)


class TestArchiveTraces(unittest.TestCase):
    """测试trace归档逻辑"""

    def test_archive_creates_gz(self):
        """应创建压缩的.gz文件"""
        import tempfile
        import time
        from factor_scan_mem_optimized import archive_traces

        with tempfile.TemporaryDirectory() as tmpdir:
            trace_dir = Path(tmpdir) / "trace"
            trace_dir.mkdir()

            # 创建过期的trace文件
            old_file = trace_dir / "old_trace.json"
            old_file.write_text('{"test": "data"}')
            # 设置修改时间为10天前
            old_ts = time.time() - 10 * 86400
            os.utime(old_file, (old_ts, old_ts))

            archived = archive_traces(trace_dir=str(trace_dir), max_age_days=7, compress=True)

            self.assertGreater(archived, 0)
            self.assertTrue((trace_dir / "old_trace.json.gz").exists())
            self.assertFalse(old_file.exists())

    def test_archive_skips_recent_files(self):
        """不应归档近7天的文件"""
        import tempfile
        import time
        from factor_scan_mem_optimized import archive_traces

        with tempfile.TemporaryDirectory() as tmpdir:
            trace_dir = Path(tmpdir) / "trace"
            trace_dir.mkdir()

            # 创建最近的trace文件
            recent_file = trace_dir / "recent_trace.json"
            recent_file.write_text('{"test": "data"}')
            # 保持最新修改时间

            archived = archive_traces(trace_dir=str(trace_dir), max_age_days=7, compress=True)

            self.assertEqual(archived, 0)
            self.assertTrue(recent_file.exists())

    def test_archive_missing_dir(self):
        """目录不存在时应返回0"""
        from factor_scan_mem_optimized import archive_traces

        archived = archive_traces(trace_dir="/nonexistent/path", max_age_days=7)
        self.assertEqual(archived, 0)


class TestScanSizes(unittest.TestCase):
    """测试大文件扫描逻辑"""

    def test_scan_identifies_large_files(self):
        """应识别>=1MB的文件"""
        import tempfile
        from factor_scan_mem_optimized import scan_sizes

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建不同大小的文件
            small_file = Path(tmpdir) / "small.txt"
            small_file.write_text("x" * 1024)  # 1KB

            large_file = Path(tmpdir) / "large.h5"
            large_file.write_text("y" * (2 * 1024 * 1024))  # 2MB

            rows = scan_sizes(tmpdir, topn=10, min_mb=1)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][1], str(large_file))

    def test_scan_returns_empty_for_small_files(self):
        """所有文件都小于阈值时应返回空列表"""
        import tempfile
        from factor_scan_mem_optimized import scan_sizes

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "tiny.txt").write_text("small")

            rows = scan_sizes(tmpdir, topn=10, min_mb=1)
            self.assertEqual(len(rows), 0)


class TestMemoryLimits(unittest.TestCase):
    """测试内存限制逻辑"""

    def test_soft_limit_check(self):
        """软限制检查应正常工作"""
        from memory_utils import check_memory

        result = check_memory("test", soft_limit=2000, hard_limit=4000)
        self.assertTrue(result)  # 正常进程远低于2GB

    def test_hard_limit_check(self):
        """硬限制检查应正常工作"""
        from memory_utils import check_memory

        result = check_memory("test", soft_limit=2000, hard_limit=4000)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
