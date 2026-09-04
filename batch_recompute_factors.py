#!/usr/bin/env python3
"""
批量更新所有因子会话到全量数据，并重新计算因子。
分两阶段执行：Phase 1 只复制数据，Phase 2 统一计算。
用法:
    source rdagent-env/bin/activate && python3 batch_recompute_factors.py [--phase1] [--phase2] [--dry-run]
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

# ── 路径配置 ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent
WS = BASE / "git_ignore_folder" / "RD-Agent_workspace"
SRC_PQ = BASE / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv_full.parquet"
SRC_H5 = BASE / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv_full.h5"
SRC_DEBUG_PQ = BASE / "git_ignore_folder" / "factor_implementation_source_data_debug" / "daily_pv.parquet"
SRC_DEBUG_H5 = BASE / "git_ignore_folder" / "factor_implementation_source_data_debug" / "daily_pv.h5"

PHASE1 = "--phase1" in sys.argv
PHASE2 = "--phase2" in sys.argv
DRY_RUN = "--dry-run" in sys.argv


def get_sessions() -> list[Path]:
    """获取所有有 factor.py 的会话目录"""
    return sorted([d for d in WS.iterdir() if d.is_dir() and (d / "factor.py").exists()])


def copy_data_to_session(session: Path) -> bool:
    """将全量数据复制到 session 目录（使用 parquet 更快）"""
    try:
        # 优先用 parquet（114MB vs 416MB），因子代码兼容两种格式
        if SRC_PQ.exists():
            # 临时写一个 helpers 让 factor.py 也能读 parquet
            dst_pq = session / "daily_pv.parquet"
            dst_h5 = session / "daily_pv.h5"
            # 先复制 parquet（小文件，快）
            shutil.copy2(SRC_PQ, dst_pq)
            # 同时生成 h5（备用，因子代码默认读 h5）
            if SRC_H5.exists():
                shutil.copy2(SRC_H5, dst_h5)
            # 清掉旧的执行锁
            lock = session / "execution.lock"
            if lock.exists():
                lock.unlink()
            pq_size = dst_pq.stat().st_size / 1024 / 1024
            print(f"  ✅ {session.name} ({pq_size:.0f}MB parquet)", flush=True)
            return True
        else:
            print(f"  ❌ {session.name}: 源 parquet 不存在", flush=True)
            return False
    except Exception as e:
        print(f"  ❌ {session.name}: {e}", flush=True)
        return False


def recompute_factor(session: Path) -> tuple[bool, str]:
    """运行 session 的 factor.py，返回 (success, info)"""
    factor_py = session / "factor.py"
    if not factor_py.exists():
        return False, "无 factor.py"

    old_cwd = os.getcwd()
    try:
        os.chdir(session)
        start = time.time()

        code = factor_py.read_text(encoding="utf-8")
        func_match = re.search(r"def\s+(\w+)\s*\(\s*\):", code)
        func_name = func_match.group(1) if func_match else None

        if func_name:
            namespace: dict = {}
            exec(compile(code, str(factor_py), "exec"), namespace)
            namespace[func_name]()
        else:
            exec(code, {})

        elapsed = time.time() - start

        result_h5 = session / "result.h5"
        result_pq = session / "result.parquet"
        if result_h5.exists():
            df = pd.read_hdf(result_h5, key="data")
        elif result_pq.exists():
            df = pd.read_parquet(result_pq)
        else:
            return False, f"无 result.h5/parquet (耗时 {elapsed:.1f}s)"
        rows = len(df)
        stocks = df.index.get_level_values("instrument").nunique()
        idx0 = df.index.names[0]
        date_min = df.index.get_level_values(idx0).min()
        date_max = df.index.get_level_values(idx0).max()
        info = f"✅ {rows:,}行, {stocks}只, {date_min.date()}~{date_max.date()}, {elapsed:.1f}s"
        return True, info

    except Exception as e:
        elapsed = time.time() - start
        return False, f"❌ 执行失败: {str(e)[:120]} ({elapsed:.1f}s)"


def main():
    print("=" * 60)
    print("批量因子重算 — 全量数据 (5,553 只)")
    print(f"模式: {'DRY RUN' if DRY_RUN else '实际执行'}")
    print(f"阶段: {'Phase 1 (复制数据)' if PHASE1 else ''} {'Phase 2 (重算因子)' if PHASE2 else ''}"
          f"{' (全部)' if not PHASE1 and not PHASE2 else ''}")
    print("=" * 60)
    print(f"源 parquet: {SRC_PQ.stat().st_size / 1024 / 1024:.0f} MB")
    print(f"源 h5:      {SRC_H5.stat().st_size / 1024 / 1024:.0f} MB")
    print()

    sessions = get_sessions()
    print(f"找到 {len(sessions)} 个因子会话\n")

    # ── Phase 1: 复制数据 ───────────────────────────────────────────────────
    if not PHASE2:
        print("━━━ Phase 1: 复制数据到各会话 ━━━")
        updated = 0
        for s in sessions:
            if DRY_RUN:
                h5 = s / "daily_pv.h5"
                old_stocks = "?"
                if h5.exists():
                    try:
                        old_stocks = pd.read_hdf(h5, key="data").index.get_level_values("instrument").nunique()
                    except Exception:
                        old_stocks = "损坏"
                print(f"  [dry] {s.name}: {old_stocks} 只 → 5,553 只")
                updated += 1
            else:
                if copy_data_to_session(s):
                    updated += 1
        print(f"\n数据复制: {updated}/{len(sessions)}\n")
        if not DRY_RUN:
            print("Phase 1 完成。运行 --phase2 开始计算因子。")
        return

    # ── Phase 2: 重算因子 ───────────────────────────────────────────────────
    print("━━━ Phase 2: 重新计算因子 ━━━")
    success_count = 0
    fail_count = 0
    results = []

    for i, s in enumerate(sessions, 1):
        name = s.name
        print(f"\n[{i}/{len(sessions)}] {name}", end=" ", flush=True)
        ok, info = recompute_factor(s)
        results.append((name, ok, info))
        if ok:
            success_count += 1
            print(info)
        else:
            fail_count += 1
            print(info)

    # ── 汇总 ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"汇总: 成功 {success_count}, 失败 {fail_count}, 共 {len(sessions)} 个")
    print("=" * 60)

    if fail_count > 0:
        print("\n失败的因子:")
        for name, ok, info in results:
            if not ok:
                print(f"  • {name}: {info}")


if __name__ == "__main__":
    main()
