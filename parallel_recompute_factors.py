#!/usr/bin/env python3
"""
并行化因子重算 — 多进程同时计算多个因子
=========================================
将 batch_recompute_factors.py 的串行执行改为多进程并行，
6个进程可同时运行，理论加速比 ~5x。

用法:
    python3 parallel_recompute_factors.py [--jobs 6] [--dry-run]
"""

import os
import sys
import time
import gc
import multiprocessing as mp
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
import numpy as np

import config as cfg

BASE = cfg.PROJECT_ROOT
WS = cfg.RDAGENT_WORKSPACE
SRC_PQ = cfg.DAILY_PV_PQ  # 使用最新数据
if not SRC_PQ.exists():
    SRC_PQ = cfg.DAILY_PV_FULL_CORRECTED_PQ  # 降级到矫正数据
if not SRC_PQ.exists():
    SRC_PQ = cfg.DAILY_PV_FULL_PQ  # 再降级
SRC_H5 = cfg.FACTOR_SOURCE / "daily_pv.h5"

MAX_JOBS = int(os.getenv("FACTOR_PARALLEL_JOBS", "6"))


def get_sessions() -> list[Path]:
    """获取所有有 factor.py 的会话目录"""
    return sorted([d for d in WS.iterdir() if d.is_dir() and (d / "factor.py").exists()])


def worker_compute(session_dir: Path) -> tuple[str, bool, str]:
    """
    在子进程中运行单个因子计算。
    每个进程独立加载数据并计算，避免共享内存问题。
    """
    factor_py = session_dir / "factor.py"
    if not factor_py.exists():
        return session_dir.name, False, "无 factor.py"

    old_cwd = os.getcwd()
    start = time.time()
    try:
        os.chdir(session_dir)

        # 独立加载数据（每个进程一份，避免共享）
        if SRC_PQ.exists():
            df = pd.read_parquet(SRC_PQ)
        elif SRC_H5.exists():
            df = pd.read_hdf(SRC_H5, key="data")
        else:
            return session_dir.name, False, "源数据不存在"

        # 构建命名空间并注入 df
        namespace: dict = {"pd": pd, "np": np, "df": df}
        code = factor_py.read_text(encoding="utf-8")

        # 提取函数名并执行
        import re
        func_match = re.search(r"def\s+(\w+)\s*\(\s*\):", code)
        if func_match:
            func_name = func_match.group(1)
            exec(compile(code, str(factor_py), "exec"), namespace)
            namespace[func_name]()
        else:
            exec(code, namespace)

        elapsed = time.time() - start

        # 检查结果
        result_h5 = session_dir / "result.h5"
        result_pq = session_dir / "result.parquet"
        if result_h5.exists():
            res_df = pd.read_hdf(result_h5, key="data")
        elif result_pq.exists():
            res_df = pd.read_parquet(result_pq)
        else:
            return session_dir.name, False, f"无结果文件 ({elapsed:.1f}s)"

        rows = len(res_df)
        stocks = res_df.index.get_level_values("instrument").nunique()
        idx0 = res_df.index.names[0]
        date_min = res_df.index.get_level_values(idx0).min()
        date_max = res_df.index.get_level_values(idx0).max()
        info = f"{rows:,}行, {stocks}只, {date_min.date()}~{date_max.date()}, {elapsed:.1f}s"
        return session_dir.name, True, info

    except Exception as e:
        elapsed = time.time() - start
        return session_dir.name, False, f"❌ {str(e)[:100]} ({elapsed:.1f}s)"
    finally:
        os.chdir(old_cwd)
        gc.collect()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="并行因子重算")
    parser.add_argument("--jobs", type=int, default=MAX_JOBS, help=f"并行进程数 (默认:{MAX_JOBS})")
    parser.add_argument("--dry-run", action="store_true", help="只检查不执行")
    args = parser.parse_args()

    jobs = min(args.jobs, 12)  # 上限12
    print("=" * 70)
    print(f"  并行因子重算  (并发进程数: {jobs})")
    print("=" * 70)
    print(f"  源数据: {SRC_PQ.stat().st_size/1024/1024:.0f}MB parquet, "
          f"{SRC_H5.stat().st_size/1024/1024:.0f}MB h5")
    print()

    sessions = get_sessions()
    print(f"  找到 {len(sessions)} 个因子会话\n")

    if args.dry_run:
        print("  [DRY RUN] 跳过实际计算")
        for s in sessions[:5]:
            print(f"    {s.name}")
        print(f"    ... 共 {len(sessions)} 个")
        return

    t0 = time.time()
    results = []
    failed = []

    # 使用进程池并行执行
    with ProcessPoolExecutor(max_workers=jobs) as executor:
        future_to_session = {
            executor.submit(worker_compute, s): s for s in sessions
        }
        completed = 0
        total = len(sessions)

        for future in as_completed(future_to_session):
            completed += 1
            session = future_to_session[future]
            try:
                name, ok, info = future.result()
            except Exception as e:
                name, ok, info = session.name, False, f"异常: {e}"

            results.append((name, ok, info))
            status = "✅" if ok else "❌"
            pct = completed * 100 // total
            print(f"  [{completed:>3}/{total}] ({pct:>3}%) {status} {name[:30]:<30} {info}", flush=True)

    elapsed = time.time() - t0

    # 汇总
    success = sum(1 for _, ok, _ in results if ok)
    fail = sum(1 for _, ok, _ in results if not ok)

    print(f"\n{'='*70}")
    print(f"  汇总: 成功 {success}, 失败 {fail}, 共 {len(results)} 个")
    print(f"  耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"  平均每个因子: {elapsed/max(success,1):.1f}s")
    print(f"{'='*70}")

    if fail > 0:
        print(f"\n  失败的因子:")
        for name, ok, info in results:
            if not ok:
                print(f"    • {name}: {info}")

    # 保存汇总
    summary = {
        "total": len(results),
        "success": success,
        "fail": fail,
        "elapsed_s": round(elapsed, 1),
        "timestamp": pd.Timestamp.now().isoformat(),
    }
    summary_path = BASE / "parallel_recompute_summary.json"
    import json
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n  💾 已保存: {summary_path}")


if __name__ == "__main__":
    main()
