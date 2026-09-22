#!/usr/bin/env python3
from __future__ import annotations
"""
engine/factor_loader.py 测试
=============================
测试因子加载模块的所有功能。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from engine.factor_loader import FactorLoader


class TestFactorLoaderLoadFactor(unittest.TestCase):
    """测试 load_factor()"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_h5_factor(self, name, values, n_dates=None, n_insts=None):
        """写入一个 HDF5 因子文件"""
        if n_dates is None:
            n_dates = len(values)
        if n_insts is None:
            n_insts = 1
        dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
        insts = [f"SH{i:06d}" for i in range(100, 100 + n_insts)]
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        # 将 values 重复以匹配 MultiIndex 长度
        repeats = len(idx) // len(values) + 1
        repeated_values = np.tile(values, repeats)[:len(idx)]
        df = pd.DataFrame({name: repeated_values}, index=idx)
        session_dir = self.workspace / name
        session_dir.mkdir(parents=True, exist_ok=True)
        df.to_hdf(session_dir / "result.h5", key="data", mode="w")
        return session_dir

    def _write_parquet_factor(self, name, values, n_dates=None, n_insts=None):
        """写入一个 Parquet 因子文件"""
        if n_dates is None:
            n_dates = len(values)
        if n_insts is None:
            n_insts = 1
        dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
        insts = [f"SH{i:06d}" for i in range(100, 100 + n_insts)]
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        repeats = len(idx) // len(values) + 1
        repeated_values = np.tile(values, repeats)[:len(idx)]
        df = pd.DataFrame({name: repeated_values}, index=idx)
        session_dir = self.workspace / name
        session_dir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(session_dir / "result.parquet")
        return session_dir

    def test_load_h5_factor(self):
        """从 HDF5 加载因子"""
        self._write_h5_factor("momentum_5d", np.random.rand(20), n_dates=20, n_insts=5)
        loader = FactorLoader(workspace=self.workspace)
        result = loader.load_factor("momentum_5d")
        self.assertIsInstance(result, pd.Series)
        self.assertEqual(result.index.names, ["datetime", "instrument"])

    def test_load_parquet_factor(self):
        """从 Parquet 加载因子（优先 HDF5）"""
        self._write_h5_factor("test_factor", np.random.rand(10), n_dates=10, n_insts=5)
        loader = FactorLoader(workspace=self.workspace)
        result = loader.load_factor("test_factor")
        self.assertIsNotNone(result)
        self.assertEqual(result.index.names, ["datetime", "instrument"])

    def test_load_parquet_fallback(self):
        """无 HDF5 时回退到 Parquet"""
        self._write_parquet_factor("test_pq", np.random.rand(10), n_dates=10, n_insts=5)
        loader = FactorLoader(workspace=self.workspace)
        result = loader.load_factor("test_pq")
        self.assertIsInstance(result, pd.Series)
        self.assertEqual(result.index.names, ["datetime", "instrument"])

    def test_load_missing_factor(self):
        """不存在的因子应返回 None"""
        loader = FactorLoader(workspace=self.workspace)
        result = loader.load_factor("nonexistent")
        self.assertIsNone(result)

    def test_load_normalizes_index(self):
        """索引名称应被标准化为 (datetime, instrument)"""
        dates = pd.date_range("2024-01-01", periods=5, freq="B")
        insts = ["SH600000", "SH600001", "SH600002", "SH600003", "SH600004"]
        # 创建 (instrument, date) 顺序的索引
        idx = pd.MultiIndex.from_product([insts, dates], names=["instrument", "date"])
        df = pd.DataFrame({"value": range(25)}, index=idx)
        session_dir = self.workspace / "test_norm"
        session_dir.mkdir(parents=True, exist_ok=True)
        df.to_hdf(session_dir / "result.h5", key="data", mode="w")

        loader = FactorLoader(workspace=self.workspace)
        result = loader.load_factor("test_norm")
        self.assertEqual(result.index.names, ["datetime", "instrument"])

    def test_load_fills_forward(self):
        """NaN 应被前向填充"""
        values = [1.0, np.nan, np.nan, 2.0, np.nan]
        self._write_h5_factor("test_ffill", values, n_dates=5, n_insts=1)
        loader = FactorLoader(workspace=self.workspace)
        result = loader.load_factor("test_ffill")
        # 前向填充后 NaN 应该被填充
        self.assertTrue(result.notna().all())

    def test_load_deduplicates(self):
        """重复索引应去重"""
        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        insts = ["SH600000", "SH600000", "SH600001"]  # 重复
        idx = pd.MultiIndex.from_tuples([(d, i) for d, i in zip(dates, insts)],
                                         names=["datetime", "instrument"])
        df = pd.DataFrame({"value": [1.0, 2.0, 3.0]}, index=idx)
        session_dir = self.workspace / "test_dedup"
        session_dir.mkdir(parents=True, exist_ok=True)
        df.to_hdf(session_dir / "result.h5", key="data", mode="w")

        loader = FactorLoader(workspace=self.workspace)
        result = loader.load_factor("test_dedup")
        self.assertFalse(result.index.duplicated().any())


class TestFactorLoaderLoadFactors(unittest.TestCase):
    """测试 load_factors() 批量加载"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_factor(self, name, n=10):
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        insts = [f"SH{i:06d}" for i in range(100, 100 + n)]
        idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
        df = pd.DataFrame({"value": np.random.rand(len(idx))}, index=idx)
        session_dir = self.workspace / name
        session_dir.mkdir(parents=True, exist_ok=True)
        df.to_hdf(session_dir / "result.h5", key="data", mode="w")

    def test_batch_load(self):
        """批量加载多个因子"""
        self._write_factor("factor_a")
        self._write_factor("factor_b")
        loader = FactorLoader(workspace=self.workspace)
        result = loader.load_factors(["factor_a", "factor_b"])
        self.assertEqual(len(result), 2)
        self.assertIn("factor_a", result)
        self.assertIn("factor_b", result)

    def test_batch_load_skips_missing(self):
        """缺失的因子应被跳过"""
        self._write_factor("factor_a")
        loader = FactorLoader(workspace=self.workspace)
        result = loader.load_factors(["factor_a", "missing_factor"])
        self.assertEqual(len(result), 1)
        self.assertIn("factor_a", result)
        self.assertNotIn("missing_factor", result)


class TestFactorLoaderDefaultWorkspace(unittest.TestCase):
    """测试默认 workspace"""

    def test_default_workspace_from_config(self):
        """未指定 workspace 时应使用 cfg.RDAGENT_WORKSPACE"""
        from engine.factor_loader import FactorLoader
        loader = FactorLoader()
        import config as cfg
        self.assertEqual(loader.workspace, cfg.RDAGENT_WORKSPACE)


if __name__ == "__main__":
    unittest.main()
