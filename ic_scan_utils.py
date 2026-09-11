#!/usr/bin/env python3
"""
因子 IC 扫描工具模块
====================
从 factor_scan_mem_optimized.py 提取的公共逻辑。
提供内存优化扫描、磁盘清理、trace归档等功能。
"""
import gc
import glob
import gzip
import os
import shutil
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

import config as cfg
from memory_utils import check_memory, rss_mb
from ic_compute import (
    load_returns_chunked, load_factor_chunked,
    compute_ic_chunked, compute_top10,
)
from feishu_notify import send_combined_report

# ═══════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════
WORKSPACE = cfg.RDAGENT_WORKSPACE
SOURCE_DEBUG = cfg.FACTOR_SOURCE_DEBUG
CLEAN_H5 = SOURCE_DEBUG / "daily_pv_clean.h5"
RETURNS_H5 = SOURCE_DEBUG / "returns_5d.h5"
RETURNS_PQ = SOURCE_DEBUG / "returns_5d.parquet"
LOOKAHEAD_IDS = {
    '3e4aa8771f2340e5a1602649bb7c07bb', 'a9358be3286b43ea84ff83c315f54547',
    '54dec2334bec4988a5b89200917dcac3', '1e3c8739f45b4179bf192e0b7918bfb8',
    '3d8b904927e248158b3ef3bf52ae0d43', '4414a9e452e44991b2434a0cb59e745e',
    '4e839e97c7b74a10a025fd048ea13d84', '5c64640e427045c3983fd3d23de776da',
    '60998d75688c43f797781fde92ac4506', '29adb6eee8e740979cff12363fb47acc',
}
SOFT_MEM_LIMIT_MB = 2000
HARD_MEM_LIMIT_MB = 4000


# ═══════════════════════════════════════════════
# IC 扫描
# ═══════════════════════════════════════════════
def scan_all_factors(soft_limit: int = SOFT_MEM_LIMIT_MB,
                     hard_limit: int = HARD_MEM_LIMIT_MB) -> List[Tuple]:
    """完整因子扫描（内存优化版）

    Returns:
        List of (factor_id, global_ic, top10_2025, n_common)
    """
    print("=" * 60)
    print("  RD-Agent 因子 IC 扫描（内存优化版）")
    print("=" * 60)
    print(f"初始内存: {rss_mb():.0f} MB\n")

    # Step 1: 分年加载 returns
    print("[Step 1] 加载 forward returns（分年）...")
    returns_by_year = load_returns_chunked(
        RETURNS_PQ if RETURNS_PQ.exists() else RETURNS_H5
    )
    total_rows = sum(len(v) for v in returns_by_year.values())
    print(f"  共 {len(returns_by_year)} 年, 总行数: {total_rows:,}")
    print(f"  内存: {rss_mb():.0f} MB\n")

    # Step 2: 逐因子扫描
    print("[Step 2] 逐因子计算 IC...")
    results = []
    skipped = 0

    for d in sorted(WORKSPACE.iterdir()):
        if not d.is_dir() or d.name in LOOKAHEAD_IDS:
            continue
        h5 = d / "result.h5"
        pq = d / "result.parquet"
        if not h5.exists() and not pq.exists():
            continue

        if not check_memory(f"因子 {d.name[:8]}...", soft_limit, hard_limit):
            skipped += 1
            continue

        try:
            factor_chunks = load_factor_chunked(
                d, chunk_years=list(returns_by_year.keys())
            )
            if not factor_chunks:
                skipped += 1
                continue

            global_ic, yearly_ic = compute_ic_chunked(factor_chunks, returns_by_year)
            yearly_top10 = compute_top10(factor_chunks, returns_by_year)

            if global_ic is None:
                skipped += 1
                continue

            n_common = sum(
                len(factor_chunks[y].loc[
                    factor_chunks[y].dropna().index.intersection(
                        returns_by_year[y].dropna().index
                    )
                ]) for y in factor_chunks if y in returns_by_year
            )

            results.append((d.name, global_ic, yearly_top10.get(2025, 0), n_common))

            if len(results) % 10 == 0:
                print(f"  已处理 {len(results)} 个因子, 内存: {rss_mb():.0f} MB")

            del factor_chunks
            gc.collect()

        except Exception as e:
            print(f"  跳过 {d.name[:8]}...: {e}")
            skipped += 1
            continue

    # Step 3: 排序并输出
    print("\n[Step 3] 生成排名...")
    results.sort(key=lambda x: abs(x[1]), reverse=True)
    print(f"\n总计: {len(results)} 个因子, 跳过 {skipped} 个, 峰值内存: {rss_mb():.0f} MB")
    print("\nTop 15:")
    print(f"  {'#':>3}  {'因子ID':>32}  {'IC':>8}  {'top10_2025':>10}")
    print("  " + "-" * 60)
    for i, (fid, ic, top10, n) in enumerate(results[:15], 1):
        print(f"  {i:>3}  {fid:>32}  {ic:>8.4f}  {top10:>+9.3f}%")

    out = Path("factor_ranking_mem_optimized.txt")
    with open(out, "w") as f:
        f.write(f"Total: {len(results)}, Skipped: {skipped}\n")
        f.write(f"Peak memory: {rss_mb():.0f} MB\n\n")
        for i, (fid, ic, top10, n) in enumerate(results, 1):
            f.write(f"{i:>3} {fid:>32} IC={ic:.4f} top10={top10:+.3f}% n={n}\n")
    print(f"\n结果已保存到: {out}")
    return results


def recompute_factor(session_dir: Path, output_pq: Optional[Path] = None) -> Optional[dict]:
    """重新计算单个因子的 IC（内存优化版）

    Returns:
        dict with {id, ic, top10_med, n_common} 或 None（失败/跳过）
    """
    if not check_memory(f"重算 {session_dir.name[:8]}", SOFT_MEM_LIMIT_MB, HARD_MEM_LIMIT_MB):
        return None

    h5 = session_dir / "result.h5"
    if not h5.exists():
        return None

    pq = session_dir / "result.parquet"
    if pq.exists():
        fs = pd.read_parquet(pq).iloc[:, 0]
    else:
        fs = pd.read_hdf(h5, key="data").iloc[:, 0]

    fs = fs[~fs.index.duplicated(keep="first")]
    fs = fs.ffill().dropna()

    src = RETURNS_PQ if RETURNS_PQ.exists() else RETURNS_H5
    r = pd.read_parquet(src).iloc[:, 0] if src.suffix == '.parquet' else pd.read_hdf(src, key="data")

    common = fs.dropna().index.intersection(r.dropna().index)
    if len(common) < 100:
        del fs, r
        gc.collect()
        return None

    f = fs.loc[common]
    ic = f.corr(r.loc[common])
    decile = f.rank(pct=True)
    top10_med = r.loc[common][decile >= 0.9].median() * 100

    out_pq = output_pq or pq
    f.to_frame("factor_value").to_parquet(out_pq, engine="pyarrow", compression="snappy")

    result = {"id": session_dir.name, "ic": ic, "top10_med": top10_med, "n_common": len(common)}
    del f, fs, r
    gc.collect()
    return result


# ═══════════════════════════════════════════════
# 磁盘清理
# ═══════════════════════════════════════════════
def cleanup_disk_space(aggressive: bool = False) -> int:
    """清理冗余文件，释放磁盘空间

    Returns:
        节省的字节数
    """
    print("\n" + "=" * 60)
    print("  磁盘空间清理")
    print("=" * 60)
    saved = 0

    for d in WORKSPACE.iterdir():
        if not d.is_dir():
            continue
        for fname in ["daily_pv_debug.h5", "daily_pv_debug.parquet"]:
            fp = d / fname
            if fp.exists():
                sz = fp.stat().st_size
                fp.unlink()
                saved += sz
    print(f"  删除 daily_pv_debug 副本: 完成, 节省 {saved/1024/1024/1024:.1f} GB")

    for d in WORKSPACE.iterdir():
        if not d.is_dir():
            continue
        h5 = d / "result.h5"
        pq = d / "result.parquet"
        if h5.exists() and pq.exists():
            sz = h5.stat().st_size
            h5.unlink()
            saved += sz
    print(f"  删除 result.h5（保留 parquet）: 完成")

    for d in WORKSPACE.iterdir():
        if not d.is_dir():
            continue
        h5 = d / "daily_pv.h5"
        if h5.exists() and not h5.is_symlink():
            sz = h5.stat().st_size
            h5.unlink()
            saved += sz
    print(f"  删除 daily_pv.h5 真实副本: 完成")

    print(f"\n  总计节省: {saved/1024/1024/1024:.1f} GB")
    return saved


def archive_traces(trace_dir: str = "./git_ignore_folder/RD-Agent_workspace/trace",
                   max_age_days: int = 7,
                   compress: bool = True) -> int:
    """归档过期 trace 文件，避免 UI 全量加载历史 trace 导致 OOM

    Returns:
        归档的文件数量
    """
    if not os.path.exists(trace_dir):
        print(f"  (trace 目录不存在: {trace_dir})")
        return 0

    threshold_ts = time.time() - max_age_days * 86400
    archived = 0
    saved = 0

    for fpath in glob.glob(os.path.join(trace_dir, "**", "*.json"), recursive=True):
        if os.path.getmtime(fpath) < threshold_ts:
            sz = os.path.getsize(fpath)
            if compress:
                gz_path = fpath + ".gz"
                with open(fpath, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                os.remove(fpath)
                saved += sz - os.path.getsize(gz_path)
            else:
                dest = os.path.join(trace_dir + "_archive", os.path.basename(fpath))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(fpath, dest)
                saved += sz
            archived += 1

    print(f"  归档 trace: {archived} 个, 节省 {saved/1024/1024:.1f} MB")
    return archived


def scan_sizes(root: str = "./git_ignore_folder/RD-Agent_workspace",
               topn: int = 30,
               min_mb: int = 1) -> List[Tuple[int, str]]:
    """扫描目录中所有 >=min_mb 的文件，按大小排序输出（诊断用）

    Returns:
        List of (size_bytes, path)
    """
    rows = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if size >= min_mb * 1024 * 1024:
                rows.append((size, p))
    rows.sort(reverse=True)
    print(f"{'size_MB':>10}  {'size_GB':>8}  path")
    for size, p in rows[:topn]:
        print(f"{size/1024/1024:10.1f}  {size/1024/1024/1024:8.3f}  {p}")
    total = sum(s for s, _ in rows)
    print(f"\n总计: {len(rows)} 个文件 >= {min_mb}MB, {total/1024/1024/1024:.2f} GB")
    return rows
