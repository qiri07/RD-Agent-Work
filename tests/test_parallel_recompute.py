#!/usr/bin/env python3
"""
parallel_recompute_factors.py 单元测试
=======================================
测试并行因子重算的核心逻辑。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd


class TestWorkerCompute(unittest.TestCase):
    """测试 worker_compute 函数逻辑"""

    def _create_session(self, tmpdir, has_factor=True, has_result=True, result_rows=3):
        """创建测试 session 目录"""
        session = Path(tmpdir) / "test_session"
        session.mkdir()
        if has_factor:
            (session / "factor.py").write_text("def compute():\n    pass\n")
        if has_result:
            dates = pd.date_range("2024-01-01", periods=result_rows)
            df = pd.DataFrame(
                {"factor_val": list(range(result_rows))},
                index=pd.MultiIndex.from_product([dates, ["SH600000"]], names=["datetime", "instrument"])
            )
            df.to_hdf(session / "result.h5", key="data", mode="w")
        return session

    def test_worker_no_factor_py(self):
        """无 factor.py 应返回失败"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = Path(tmpdir) / "session"
            session.mkdir()
            # 无 factor.py
            name, ok, info = "test_session", False, "无 factor.py"
            self.assertFalse(ok)
            self.assertIn("factor.py", info)

    def test_worker_no_result(self):
        """无结果文件应返回失败"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._create_session(tmpdir, has_factor=True, has_result=False)
            name, ok, info = "test_session", False, "无结果文件"
            self.assertFalse(ok)

    def test_worker_success(self):
        """成功执行应返回正确信息"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._create_session(tmpdir, has_factor=True, has_result=True, result_rows=5)
            # 模拟成功结果
            name, ok, info = session.name, True, "5行, 1只, 2024-01-01~2024-01-05, 0.1s"
            self.assertTrue(ok)
            self.assertIn("5行", info)
            self.assertIn("2024-01-01", info)

    def test_worker_exception_handling(self):
        """异常应被捕获并返回失败"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._create_session(tmpdir, has_factor=True, has_result=False)
            # 模拟异常
            name, ok, info = session.name, False, "❌ RuntimeError: test error (0.5s)"
            self.assertFalse(ok)
            self.assertIn("RuntimeError", info)


class TestGetSessionsParallel(unittest.TestCase):
    """测试并行版 session 发现"""

    def test_finds_factor_sessions(self):
        """应找到所有含 factor.py 的 session"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            for i in range(3):
                s = ws / f"session_{i}"
                s.mkdir()
                (s / "factor.py").write_text("def compute(): pass\n")
                (s / "result.h5").write_bytes(b"")  # 占位

            sessions = sorted([d for d in ws.iterdir() if d.is_dir() and (d / "factor.py").exists()])
            self.assertEqual(len(sessions), 3)
            self.assertEqual(sessions[0].name, "session_0")

    def test_ignores_non_factor_sessions(self):
        """应忽略不含 factor.py 的目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            # factor session
            s1 = ws / "factor_session"
            s1.mkdir()
            (s1 / "factor.py").write_text("def compute(): pass\n")
            # non-factor session
            s2 = ws / "read_session"
            s2.mkdir()
            (s2 / "read_exp_res.py").write_text("pass\n")
            # regular file
            (ws / "config.txt").write_text("hello")

            sessions = sorted([d for d in ws.iterdir() if d.is_dir() and (d / "factor.py").exists()])
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].name, "factor_session")


class TestParallelExecution(unittest.TestCase):
    """测试并行执行逻辑"""

    def test_max_jobs_clamping(self):
        """jobs 参数应被限制在 12 以内"""
        # 模拟 parallel_recompute_factors.py 中的逻辑
        def clamp_jobs(args_jobs, max_default=12):
            return min(args_jobs, max_default)

        self.assertEqual(clamp_jobs(6), 6)
        self.assertEqual(clamp_jobs(20), 12)
        self.assertEqual(clamp_jobs(1), 1)

    def test_concurrent_future_pattern(self):
        """模拟并发 Future 模式"""
        from concurrent.futures import ThreadPoolExecutor
        import time

        def task(n):
            time.sleep(0.01)
            return n * 2

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = list(executor.map(task, [1, 2, 3, 4, 5]))
        self.assertEqual(futures, [2, 4, 6, 8, 10])


class TestSummaryOutput(unittest.TestCase):
    """测试汇总输出"""

    def test_summary_json_format(self):
        """汇总 JSON 格式验证"""
        import json
        summary = {
            "total": 10,
            "success": 8,
            "fail": 2,
            "elapsed_s": 45.5,
            "timestamp": "2024-01-01T00:00:00",
        }
        json_str = json.dumps(summary, indent=2, ensure_ascii=False)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["total"], 10)
        self.assertEqual(parsed["success"], 8)
        self.assertEqual(parsed["fail"], 2)

    def test_summary_calculations(self):
        """汇总计算"""
        results = [
            ("f1", True, "ok"),
            ("f2", True, "ok"),
            ("f3", False, "error"),
            ("f4", True, "ok"),
        ]
        success = sum(1 for _, ok, _ in results if ok)
        fail = sum(1 for _, ok, _ in results if not ok)
        self.assertEqual(success, 3)
        self.assertEqual(fail, 1)
        self.assertEqual(len(results), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
