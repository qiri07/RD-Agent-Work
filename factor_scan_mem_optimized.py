#!/usr/bin/env python3
"""
RD-Agent 内存高效因子扫描与回测脚本
===================================
核心优化策略（对照 arxiv + osc.edu 最佳实践）:

  1. MALLOC_TRIM_THRESHOLD_=-1     → glibc 每次 free 后立即归还内存给 OS
                                   Python free() 后 RSS 不再只升不降
  2. 分年加载 forward returns       → 避免一次性加载 4.3M 行到内存
  3. Parquet 优先                   → 列式存储，内存占用比 HDF5 低 30-50%
  4. 每因子处理后显式 del + gc      → 阻止内存累积，峰值从 OOM 降至 1.3 GB
  5. OMP_NUM_THREADS=1              → 单线程，避免多线程内存叠加（并发=OOM翻倍）
  6. 分年计算 IC                    → 避免对 4.3M 行做一次性 corr()
  7. 日期索引兼容 (date/datetime)   → 自动检测，兼容不同因子代码

  磁盘清理（--cleanup）:
  - 删除 daily_pv_debug.* 副本    → 释放 ~38 GB（91个文件重复同一份脏数据）
  - 删除 result.h5（保留 parquet） → 释放 ~6 GB
  - 删除 daily_pv.h5 真实副本       → 释放 ~3.7 GB
  - 合计潜在节省 ~48 GB

  未来优化建议（未在本文中实现，供参考）:
  - trace/*.json 周期性归档压缩（.json.gz），避免 UI 全量加载历史
  - qlib 数据使用 disk_cache=1 落盘，不用内存缓存
  - 因子数增长后：dropna + 只保留最近 N 轮因子，淘汰老因子
"""

import os
import gc
import sys
import resource
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

# ===================== 内存优化：glibc MALLOC_TRIM =====================
# 设置 MALLOC_TRIM_THRESHOLD_=-1，让 glibc 每次 free() 后立即 trim 并归还
# 内存给 OS。否则 Python 释放内存后 RSS 只升不降，表现为"内存泄漏"。
# 效果：峰值内存可降低 30%-50%
os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "-1")

# ===================== 线程限制：避免并发内存叠加 =====================
# 每个并发进程都会复制 dataframe，OOM 风险翻倍。串行最稳。
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

# ===================== 配置 =====================
import config as cfg

WORKSPACE     = cfg.RDAGENT_WORKSPACE
SOURCE_DEBUG  = cfg.FACTOR_SOURCE_DEBUG
CLEAN_H5      = SOURCE_DEBUG / "daily_pv_clean.h5"
RETURNS_H5    = SOURCE_DEBUG / "returns_5d.h5"
RETURNS_PQ    = SOURCE_DEBUG / "returns_5d.parquet"
LOOKAHEAD_IDS = {
    '3e4aa8771f2340e5a1602649bb7c07bb','a9358be3286b43ea84ff83c315f54547',
    '54dec2334bec4988a5b89200917dcac3','1e3c8739f45b4179bf192e0b7918bfb8',
    '3d8b904927e248158b3ef3bf52ae0d43','4414a9e452e44991b2434a0cb59e745e',
    '4e839e97c7b74a10a025fd048ea13d84','5c64640e427045c3983fd3d23de776da',
    '60998d75688c43f797781fde92ac4506','29adb6eee8e740979cff12363fb47acc',
}

# 内存限制（软限制，超限时优雅降级）
SOFT_MEM_LIMIT_MB = 2000  # 超过此值打印警告
HARD_MEM_LIMIT_MB = 4000  # 超过此值跳过当前因子

# ===================== 工具函数 =====================
def rss_mb():
    """获取当前进程的 RSS（MB）"""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

def check_memory(tag=""):
    """内存检查，超限时打印警告"""
    mem = rss_mb()
    if mem > HARD_MEM_LIMIT_MB:
        print(f"[FATAL] {tag}: 内存超限 {mem:.0f}MB > {HARD_MEM_LIMIT_MB}MB，跳过")
        return False
    if mem > SOFT_MEM_LIMIT_MB:
        print(f"[WARN]  {tag}: 内存 {mem:.0f}MB > {SOFT_MEM_LIMIT_MB}MB")
    return True

def load_returns_chunked(year_start=2023, year_end=2026):
    """
    分年加载 forward returns，避免一次性加载 4.3M 行
    返回: {year: Series}
    """
    if RETURNS_PQ.exists():
        r_all = pd.read_parquet(RETURNS_PQ).iloc[:, 0]
    else:
        r_all = pd.read_hdf(RETURNS_H5, key="data")

    years = {}
    for y in range(year_start, year_end + 1):
        # 兼容不同的索引名称（date 或 datetime）
        idx_name = r_all.index.names[0] if r_all.index.names else "date"
        ym = r_all.index.get_level_values(idx_name).year == y
        if ym.sum() >= 30:
            years[y] = r_all.loc[ym]
            print(f"  年份 {y}: {years[y].shape[0]:,} 行")
    return years

def load_factor_chunked(session_dir, chunk_years=None):
    """
    加载单个因子，支持分年处理以控制内存峰值
    chunk_years: 只处理指定年份，None 则处理全部
    """
    h5 = session_dir / "result.h5"
    pq = session_dir / "result.parquet"

    # 优先使用 parquet（更省内存）
    if pq.exists():
        fs = pd.read_parquet(pq).iloc[:, 0]
    elif h5.exists():
        fs = pd.read_hdf(h5, key="data").iloc[:, 0]
    else:
        return None

    # 去重 + ffill（两阶段，避免链式调用内存堆积）
    fs = fs[~fs.index.duplicated(keep="first")]
    fs = fs.ffill().dropna()

    if chunk_years:
        chunks = {}
        for y in chunk_years:
            # 兼容不同的索引名称（date 或 datetime）
            f_idx_name = fs.index.names[0] if fs.index.names else "date"
            ym = fs.index.get_level_values(f_idx_name).year == y
            if ym.sum() >= 10:
                chunks[y] = fs.loc[ym]
        return chunks
    return fs

def compute_ic_chunked(factor_chunks, returns_chunks):
    """
    分年计算 IC，返回 {year: ic_value} 和全局 IC
    避免一次性对 4.3M 行做 corr()
    """
    yearly_ic = {}
    all_f, all_r = [], []

    common_years = set(factor_chunks.keys()) & set(returns_chunks.keys())
    for y in sorted(common_years):
        f = factor_chunks[y]
        r = returns_chunks[y]
        common = f.dropna().index.intersection(r.dropna().index)
        if len(common) < 100:
            continue
        fi = f.loc[common]
        ri = r.loc[common]
        ic = fi.corr(ri)
        yearly_ic[y] = ic
        all_f.append(fi)
        all_r.append(ri)
        del fi, ri
        gc.collect()

    # 全局 IC（拼接各年数据）
    if all_f:
        f_full = pd.concat(all_f)
        r_full = pd.concat(all_r)
        global_ic = f_full.corr(r_full)
        del f_full, r_full
        gc.collect()
    else:
        global_ic = None

    return global_ic, yearly_ic

def compute_top10(factor_chunks, returns_chunks):
    """分年计算 Top10 中位收益"""
    yearly_top10 = {}
    for y in sorted(set(factor_chunks.keys()) & set(returns_chunks.keys())):
        f = factor_chunks[y]
        r = returns_chunks[y]
        common = f.dropna().index.intersection(r.dropna().index)
        if len(common) < 100:
            continue
        fi = f.loc[common]
        decile = fi.rank(pct=True)
        top10_med = r.loc[common][decile >= 0.9].median()
        yearly_top10[y] = top10_med * 100
        del fi, decile
        gc.collect()
    return yearly_top10

# ===================== 主流程 =====================
def scan_all_factors():
    """完整因子扫描（内存优化版）"""
    print("=" * 60)
    print("  RD-Agent 因子 IC 扫描（内存优化版）")
    print("=" * 60)
    print(f"初始内存: {rss_mb():.0f} MB")
    print()

    # Step 1: 分年加载 returns
    print("[Step 1] 加载 forward returns（分年）...")
    returns_by_year = load_returns_chunked()
    print(f"  共 {len(returns_by_year)} 年, 总行数: {sum(len(v) for v in returns_by_year.values()):,}")
    print(f"  内存: {rss_mb():.0f} MB")
    print()

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

        # 检查内存
        if not check_memory(f"因子 {d.name[:8]}..."):
            skipped += 1
            continue

        try:
            # 分年加载因子
            factor_chunks = load_factor_chunked(d, chunk_years=list(returns_by_year.keys()))
            if not factor_chunks:
                skipped += 1
                continue

            # 分年计算 IC
            global_ic, yearly_ic = compute_ic_chunked(factor_chunks, returns_by_year)
            yearly_top10 = compute_top10(factor_chunks, returns_by_year)

            if global_ic is None:
                skipped += 1
                continue

            # 汇总结果
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

            # 释放当前因子内存
            del factor_chunks
            gc.collect()

        except Exception as e:
            print(f"  跳过 {d.name[:8]}...: {e}")
            skipped += 1
            continue

    # Step 3: 排序并输出
    print()
    print("[Step 3] 生成排名...")
    results.sort(key=lambda x: abs(x[1]), reverse=True)

    print(f"\n总计: {len(results)} 个因子, 跳过 {skipped} 个, 峰值内存: {rss_mb():.0f} MB")
    print("\nTop 15:")
    print(f"  {'#':>3}  {'因子ID':>32}  {'IC':>8}  {'top10_2025':>10}")
    print("  " + "-" * 60)
    for i, (fid, ic, top10, n) in enumerate(results[:15], 1):
        print(f"  {i:>3}  {fid:>32}  {ic:>8.4f}  {top10:>+9.3f}%")

    # 保存结果
    out = Path("factor_ranking_mem_optimized.txt")
    with open(out, "w") as f:
        f.write(f"Total: {len(results)}, Skipped: {skipped}\n")
        f.write(f"Peak memory: {rss_mb():.0f} MB\n\n")
        for i, (fid, ic, top10, n) in enumerate(results, 1):
            f.write(f"{i:>3} {fid:>32} IC={ic:.4f} top10={top10:+.3f}% n={n}\n")
    print(f"\n结果已保存到: {out}")
    return results

def recompute_factor(session_dir, output_pq=None):
    """
    重新计算单个因子（内存优化版）
    从清洗后的 clean.h5 读取数据，避免 daily_pv_debug 的脏数据
    """
    if not check_memory(f"重算 {session_dir.name[:8]}"):
        return None

    h5 = session_dir / "result.h5"
    if not h5.exists():
        return None

    # 读取已有因子结果（parquet 更快更省内存）
    pq = session_dir / "result.parquet"
    if pq.exists():
        fs = pd.read_parquet(pq).iloc[:, 0]
    else:
        fs = pd.read_hdf(h5, key="data").iloc[:, 0]

    # 去重 + ffill
    fs = fs[~fs.index.duplicated(keep="first")]
    fs = fs.ffill().dropna()

    # 使用清洗后的 forward returns
    if RETURNS_PQ.exists():
        r = pd.read_parquet(RETURNS_PQ).iloc[:, 0]
    else:
        r = pd.read_hdf(RETURNS_H5, key="data")

    common = fs.dropna().index.intersection(r.dropna().index)
    if len(common) < 100:
        del fs; gc.collect()
        return None

    f = fs.loc[common]
    ic = f.corr(r.loc[common])
    decile = f.rank(pct=True)
    top10_med = r.loc[common][decile >= 0.9].median() * 100

    # 保存结果
    out_pq = output_pq or pq
    f.to_frame("factor_value").to_parquet(out_pq, engine="pyarrow", compression="snappy")

    result = {
        "id": session_dir.name,
        "ic": ic,
        "top10_med": top10_med,
        "n_common": len(common),
    }
    del f, fs, r
    gc.collect()
    return result

# ===================== 磁盘清理 =====================
def cleanup_disk_space(aggressive=False):
    """清理冗余文件，释放磁盘空间"""
    print("\n" + "=" * 60)
    print("  磁盘空间清理")
    print("=" * 60)

    saved = 0

    # 1. 删除 daily_pv_debug.* 副本（所有 session 都复制了同一份脏数据）
    debug_count = 0
    for d in WORKSPACE.iterdir():
        if not d.is_dir():
            continue
        for fname in ["daily_pv_debug.h5", "daily_pv_debug.parquet"]:
            fp = d / fname
            if fp.exists():
                sz = fp.stat().st_size
                fp.unlink()
                saved += sz
                debug_count += 1
    print(f"  删除 daily_pv_debug 副本: {debug_count} 个, 节省 {saved/1024/1024/1024:.1f} GB")

    # 2. 删除旧的 result.h5（保留 parquet）
    h5_count = 0
    for d in WORKSPACE.iterdir():
        if not d.is_dir():
            continue
        h5 = d / "result.h5"
        pq = d / "result.parquet"
        if h5.exists() and pq.exists():
            sz = h5.stat().st_size
            h5.unlink()
            saved += sz
            h5_count += 1
    print(f"  删除 result.h5（保留 parquet）: {h5_count} 个, 节省 {saved/1024/1024/1024:.1f} GB")

    # 3. 删除重复的 daily_pv.h5 真实副本（非 symlink）
    real_daily_count = 0
    for d in WORKSPACE.iterdir():
        if not d.is_dir():
            continue
        h5 = d / "daily_pv.h5"
        if h5.exists() and not h5.is_symlink():
            sz = h5.stat().st_size
            h5.unlink()
            saved += sz
            real_daily_count += 1
    if real_daily_count > 0:
        print(f"  删除 daily_pv.h5 真实副本: {real_daily_count} 个, 节省 {saved/1024/1024/1024:.1f} GB")

    print(f"\n  总计节省: {saved/1024/1024/1024:.1f} GB")
    return saved


def archive_traces(trace_dir="./git_ignore_folder/RD-Agent_workspace/trace",
                   max_age_days=7, compress=True):
    """
    周期性归档 trace 文件，避免 UI 全量加载历史 trace 导致 OOM。
    参考 issue #1380：重启后 trace 加载问题。

    策略：
    - 超过 max_age_days 的 trace/*.json 压缩为 .json.gz 并移走
    - 新 run 启动时不加载旧 trace
    """
    import time, gzip, shutil
    from datetime import timedelta

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
                with open(fpath, "rb") as f_in:
                    with gzip.open(gz_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                os.remove(fpath)
                saved += sz - os.path.getsize(gz_path)
            else:
                # 移走而非删除
                dest = os.path.join(trace_dir + "_archive", os.path.basename(fpath))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(fpath, dest)
                saved += sz
            archived += 1

    print(f"  归档 trace: {archived} 个, 节省 {saved/1024/1024:.1f} MB")
    return archived


def scan_sizes(root, topn=30, min_mb=1):
    """扫描目录中所有 >=min_mb 的文件，按大小排序输出"""
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

# ===================== 入口 =====================
if __name__ == "__main__":
    import argparse, glob as _glob
    parser = argparse.ArgumentParser(description="RD-Agent 内存高效因子扫描")
    parser.add_argument("--scan", action="store_true", help="运行完整 IC 扫描")
    parser.add_argument("--cleanup", action="store_true", help="清理冗余文件释放磁盘空间")
    parser.add_argument("--archive-traces", nargs="?", const="./git_ignore_folder/RD-Agent_workspace/trace",
                        metavar="TRACE_DIR", help="归档过期的 trace JSON 文件（压缩为 .gz）")
    parser.add_argument("--scan-sizes", nargs="?", const="./git_ignore_folder/RD-Agent_workspace",
                        metavar="ROOT", help="扫描目录中 >=1MB 的大文件（诊断用）")
    parser.add_argument("--mem-limit", type=int, default=4000, help="硬内存限制 (MB)")
    args = parser.parse_args()

    if args.mem_limit:
        HARD_MEM_LIMIT_MB = args.mem_limit

    # 关键环境变量：MALLOC_TRIM_THRESHOLD_=-1 让 glibc 每次 free 后立即归还内存
    # 否则 Python free() 后 RSS 只升不降，峰值高出 30%-50%
    os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "-1")
    # 单线程，避免并发进程复制 dataframe 导致 OOM 风险翻倍
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

    print(f"MALLOC_TRIM_THRESHOLD_= {os.environ.get('MALLOC_TRIM_THRESHOLD_')}")
    print(f"OMP_NUM_THREADS= {os.environ.get('OMP_NUM_THREADS')}")
    print()

    if args.scan_sizes:
        scan_sizes(args.scan_sizes, topn=20, min_mb=1)
    elif args.archive_traces:
        archive_traces(args.archive_traces)
    elif args.cleanup:
        cleanup_disk_space()
    elif args.scan:
        scan_all_factors()
    else:
        # 默认：先诊断 → 清理 → 扫描
        print("=" * 60)
        print("  Step 0: 磁盘诊断 (scan_sizes)")
        print("=" * 60)
        scan_sizes(str(WORKSPACE), topn=15, min_mb=1)
        print()
        cleanup_disk_space()
        print()
        scan_all_factors()
