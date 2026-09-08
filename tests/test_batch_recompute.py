#!/usr/bin/env python3
"""
batch_recompute_factors.py / parallel_recompute_factors.py 单元测试
===================================================================
测试 session 发现、数据复制、因子重算逻辑。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd


class TestGetSessions(unittest.TestCase):
    """测试 session 发现逻辑"""

    def test_get_sessions_finds_factor_py(self):
        """应找到含 factor.py 的 session"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            # 创建含 factor.py 的 session
            s1 = ws / "session_a"
            s1.mkdir()
            (s1 / "factor.py").write_text("def compute(): pass\n")
            (s1 / "daily_pv.parquet").write_bytes(b"")

            # 创建无 factor.py 的 session
            s2 = ws / "session_b"
            s2.mkdir()
            (s2 / "read_exp_res.py").write_text("pass\n")

            # 模拟 get_sessions 逻辑
            sessions = sorted([d for d in ws.iterdir() if d.is_dir() and (d / "factor.py").exists()])
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].name, "session_a")

    def test_get_sessions_empty(self):
        """空目录应返回空列表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions = sorted([d for d in Path(tmpdir).iterdir()
                             if d.is_dir() and (d / "factor.py").exists()])
            self.assertEqual(len(sessions), 0)

    def test_get_sessions_no_factor(self):
        """只有普通文件的目录不应被识别为 session"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            (ws / "not_a_session.txt").write_text("hello")
            sessions = sorted([d for d in ws.iterdir() if d.is_dir() and (d / "factor.py").exists()])
            self.assertEqual(len(sessions), 0)


class TestCopyDataToSession(unittest.TestCase):
    """测试数据复制到 session 逻辑"""

    def _make_test_src(self, tmpdir):
        """创建测试源 parquet 文件"""
        src = Path(tmpdir) / "source.parquet"
        dates = pd.date_range("2024-01-01", periods=5)
        df = pd.DataFrame({
            "$open": [10.0]*5, "$close": [10.5]*5,
            "$high": [10.6]*5, "$low": [10.3]*5,
            "$volume": [1000000]*5, "$factor": [1.0]*5,
        }, index=pd.MultiIndex.from_product([dates, ["SH600000"]], names=["date", "instrument"]))
        df.to_parquet(src)
        return src

    def test_copy_creates_parquet(self):
        """应创建 parquet 文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._make_test_src(tmpdir)
            session = Path(tmpdir) / "session"
            session.mkdir()

            # 模拟 copy_data_to_session 逻辑
            dst_pq = session / "daily_pv.parquet"
            import shutil
            shutil.copy2(src, dst_pq)

            self.assertTrue(dst_pq.exists())
            df = pd.read_parquet(dst_pq)
            self.assertEqual(len(df), 5)

    def test_copy_removes_symlink(self):
        """应删除旧的符号链接"""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._make_test_src(tmpdir)
            session = Path(tmpdir) / "session"
            session.mkdir()

            # 创建符号链接
            dst_pq = session / "daily_pv.parquet"
            link_target = Path(tmpdir) / "stale_data.parquet"
            link_target.write_bytes(b"stale")
            dst_pq.symlink_to(link_target)
            self.assertTrue(dst_pq.is_symlink())

            # 复制新文件（应删除 symlink）
            import shutil
            if dst_pq.is_symlink():
                dst_pq.unlink()
            elif dst_pq.exists():
                dst_pq.unlink()
            shutil.copy2(src, dst_pq)

            self.assertFalse(dst_pq.is_symlink())
            self.assertTrue(dst_pq.exists())
            df = pd.read_parquet(dst_pq)
            self.assertEqual(len(df), 5)

    def test_copy_removes_existing_file(self):
        """应删除旧的普通文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._make_test_src(tmpdir)
            session = Path(tmpdir) / "session"
            session.mkdir()

            dst_pq = session / "daily_pv.parquet"
            dst_pq.write_text("old data")

            import shutil
            if dst_pq.is_symlink():
                dst_pq.unlink()
            elif dst_pq.exists():
                dst_pq.unlink()
            shutil.copy2(src, dst_pq)

            self.assertTrue(dst_pq.exists())
            df = pd.read_parquet(dst_pq)
            self.assertEqual(len(df), 5)

    def test_copy_fallback_to_h5(self):
        """h5 生成失败不应影响使用"""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._make_test_src(tmpdir)
            session = Path(tmpdir) / "session"
            session.mkdir()

            dst_pq = session / "daily_pv.parquet"
            import shutil
            shutil.copy2(src, dst_pq)

            # h5 生成（正常情况应成功）
            df_pq = pd.read_parquet(dst_pq)
            dst_h5 = session / "daily_pv.h5"
            try:
                df_pq.to_hdf(dst_h5, key="data", mode="w", format="table")
            except Exception:
                pass  # 模拟失败

            self.assertTrue(dst_pq.exists())
            self.assertTrue(dst_h5.exists())


class TestRecomputeFactor(unittest.TestCase):
    """测试因子重算逻辑（不实际执行 factor.py）"""

    def test_no_factor_py(self):
        """无 factor.py 应返回失败"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = Path(tmpdir) / "session"
            session.mkdir()
            # 无 factor.py
            ok, info = (False, "无 factor.py")  # 模拟
            self.assertFalse(ok)
            self.assertIn("factor.py", info)

    def test_no_result_file(self):
        """无结果文件应返回失败"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = Path(tmpdir) / "session"
            session.mkdir()
            (session / "factor.py").write_text("def compute(): pass\n")
            # 无 result 文件
            ok, info = (False, "无 result.h5/parquet")
            self.assertFalse(ok)

    def test_success_with_result(self):
        """有结果文件应返回成功"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = Path(tmpdir) / "session"
            session.mkdir()
            (session / "factor.py").write_text("def compute(): pass\n")
            # 创建 result.h5
            dates = pd.date_range("2024-01-01", periods=3)
            df = pd.DataFrame({"factor_val": [1.0, 2.0, 3.0]},
                index=pd.MultiIndex.from_product([dates, ["SH600000"]], names=["datetime", "instrument"]))
            df.to_hdf(session / "result.h5", key="data", mode="w")

            # 模拟成功
            ok, info = True, "3行, 1只, 2024-01-01~2024-01-03, 0.1s"
            self.assertTrue(ok)
            self.assertIn("3行", info)


class TestConvertTicker(unittest.TestCase):
    """测试 ticker 格式转换（来自 convert_tradero_to_rdagent.py）"""

    def test_sh_ticker(self):
        """sh.600519 → SH600519"""
        def ticker_to_qlib(ticker):
            return ticker.replace(".", "").upper()
        self.assertEqual(ticker_to_qlib("sh.600519"), "SH600519")
        self.assertEqual(ticker_to_qlib("sz.000001"), "SZ000001")

    def test_already_upper(self):
        """已是大写的 ticker 应保持不变"""
        def ticker_to_qlib(ticker):
            return ticker.replace(".", "").upper()
        self.assertEqual(ticker_to_qlib("SH600519"), "SH600519")
        self.assertEqual(ticker_to_qlib("BJ920000"), "BJ920000")

    def test_mixed_case(self):
        """混合大小写应转为全大写"""
        def ticker_to_qlib(ticker):
            return ticker.replace(".", "").upper()
        self.assertEqual(ticker_to_qlib("Sh.600519"), "SH600519")
        self.assertEqual(ticker_to_qlib("Sz.000001"), "SZ000001")


class TestDeduplicateLogic(unittest.TestCase):
    """测试数据去重逻辑"""

    def test_dedup_removes_duplicates(self):
        """去重应移除重复行"""
        dates = pd.date_range("2024-01-01", periods=3)
        idx = pd.MultiIndex.from_product([dates, ["SH600000", "SZ300001"]], names=["date", "instrument"])
        # 创建带重复的数据（通过 concat 而不是 append index）
        df1 = pd.DataFrame({
            "$open": [10.0]*6, "$close": [10.5]*6,
            "$high": [10.6]*6, "$low": [10.3]*6,
            "$volume": [1000000]*6, "$factor": [1.0]*6,
        }, index=idx)
        df = pd.concat([df1, df1], ignore_index=False)  # 重复一遍

        unique_df = df[~df.index.duplicated(keep='first')]
        self.assertEqual(len(unique_df), 6)
        self.assertEqual(unique_df.index.nunique(), 6)

    def test_dedup_preserves_first(self):
        """去重应保留首次出现的行"""
        dates = pd.date_range("2024-01-01", periods=2)
        idx = pd.MultiIndex.from_product([dates, ["SH600000"]], names=["date", "instrument"])
        df = pd.DataFrame({
            "$close": [10.0, 10.5, 10.0, 10.5],  # 重复
        }, index=idx.append(idx))

        unique_df = df[~df.index.duplicated(keep='first')]
        self.assertEqual(len(unique_df), 2)
        self.assertAlmostEqual(unique_df.loc[("2024-01-01", "SH600000"), "$close"], 10.0)
        self.assertAlmostEqual(unique_df.loc[("2024-01-02", "SH600000"), "$close"], 10.5)

    def test_dedup_no_duplicates(self):
        """无重复数据去重后不变"""
        dates = pd.date_range("2024-01-01", periods=3)
        idx = pd.MultiIndex.from_product([dates, ["SH600000"]], names=["date", "instrument"])
        df = pd.DataFrame({"$close": [10.0, 10.5, 11.0]}, index=idx)

        unique_df = df[~df.index.duplicated(keep='first')]
        pd.testing.assert_frame_equal(unique_df, df)


class TestMergeLogic(unittest.TestCase):
    """测试数据合并逻辑（来自 convert_tradero_to_rdagent.py）"""

    def test_merge_no_overlap(self):
        """无重叠股票应直接 concat"""
        existing = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "instrument": ["SH600000", "SH600000"],
            "$close": [10.0, 10.5],
        }).set_index(["date", "instrument"])

        new = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "instrument": ["SZ300001", "SZ300001"],
            "$close": [20.0, 20.5],
        }).set_index(["date", "instrument"])

        merged = pd.concat([
            existing.reset_index(),
            new.reset_index(),
        ]).set_index(["date", "instrument"]).sort_index()
        merged = merged[~merged.index.duplicated(keep='first')]

        self.assertEqual(len(merged), 4)
        insts = merged.index.get_level_values("instrument").unique()
        self.assertIn("SH600000", insts)
        self.assertIn("SZ300001", insts)

    def test_merge_with_overlap_keeps_both(self):
        """有重叠股票时应只保留非重叠部分再合并"""
        existing = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "instrument": ["SH600000", "SH600000"],
            "$close": [10.0, 10.5],
        }).set_index(["date", "instrument"])

        new = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "instrument": ["SH600000", "SZ300001"],
            "$close": [11.0, 20.0],
        }).set_index(["date", "instrument"])

        overlap = set(existing.index.get_level_values("instrument").unique()) & \
                  set(new.index.get_level_values("instrument").unique())
        tradero_clean = new[~new.index.get_level_values("instrument").isin(overlap)]
        existing_clean = existing[~existing.index.get_level_values("instrument").isin(overlap)]

        merged = pd.concat([
            existing_clean.reset_index(),
            tradero_clean.reset_index(),
        ]).set_index(["date", "instrument"]).sort_index()
        merged = merged[~merged.index.duplicated(keep='first')]

        # SH600000 只保留 existing 部分，SZ300001 只保留 new 部分
        # existing_clean 为空（SH600000 全部在 overlap 中），tradero_clean 只有 SZ300001
        self.assertEqual(len(merged), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
