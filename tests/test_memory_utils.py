#!/usr/bin/env python3
"""
memory_utils.py 单元测试
========================
测试内存管理工具函数。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_utils import rss_mb, check_memory, setup_memory_env


class TestRSSMB(unittest.TestCase):
    """测试 RSS 获取"""

    def test_returns_positive_float(self):
        mem = rss_mb()
        self.assertIsInstance(mem, float)
        self.assertGreater(mem, 0)

    def test_consistent_across_calls(self):
        """连续调用应返回相近值（±50% 以内）"""
        m1 = rss_mb()
        m2 = rss_mb()
        self.assertGreater(m1, 0)
        self.assertGreater(m2, 0)
        ratio = max(m1, m2) / min(m1, m2)
        self.assertLess(ratio, 2.0)


class TestCheckMemory(unittest.TestCase):
    """测试内存检查"""

    def test_pass_with_high_limits(self):
        """大限值应通过"""
        result = check_memory("test", soft_limit=99999, hard_limit=99999)
        self.assertTrue(result)

    def test_warn_above_soft_limit(self):
        """超 soft limit 应打印警告但继续"""
        # soft=1MB 几乎必然触发
        result = check_memory("test_warn", soft_limit=1, hard_limit=99999)
        # 返回 bool，不抛出异常
        self.assertIsInstance(result, bool)

    def test_return_type_is_bool(self):
        """返回值应为 bool"""
        result = check_memory("test", soft_limit=10, hard_limit=20)
        self.assertIsInstance(result, bool)


class TestSetupMemoryEnv(unittest.TestCase):
    """测试环境变量设置"""

    def test_sets_threads_to_one(self):
        """应设置 OMP/MKL/OPENBLAS 线程数为 1"""
        import os
        setup_memory_env()
        self.assertEqual(os.getenv("OMP_NUM_THREADS"), "1")
        self.assertEqual(os.getenv("MKL_NUM_THREADS"), "1")
        self.assertEqual(os.getenv("OPENBLAS_NUM_THREADS"), "1")
        self.assertEqual(os.getenv("NUMEXPR_NUM_THREADS"), "1")

    def test_does_not_override_existing(self):
        """不应覆盖已设置的值"""
        import os
        os.environ["OMP_NUM_THREADS"] = "4"
        setup_memory_env()
        self.assertEqual(os.getenv("OMP_NUM_THREADS"), "4")
        del os.environ["OMP_NUM_THREADS"]


if __name__ == "__main__":
    import os
    unittest.main(verbosity=2)
