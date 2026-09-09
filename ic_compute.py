#!/usr/bin/env python3
"""
因子IC计算核心模块
=================
从 factor_scan_mem_optimized.py 和 run_ic_fast.py 提取的公共IC计算逻辑。
避免重复实现，保证结果一致。
"""

import gc
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from memory_utils import rss_mb, check_memory


# ═══════════════════════════════════════════════
# 数据加载工具
# ═══════════════════════════════════════════════
def load_returns_chunked(source_path: Path, year_start=2023, year_end=2026) -> dict | None:
    """
    分年加载 forward returns，避免一次性加载大文件到内存
    返回: {year: Series} 或 None（当文件不存在时）
    """
    if not source_path.exists():
        print(f"[WARN] 返回数据文件不存在: {source_path}")
        return None

    if source_path.suffix == '.parquet':
        r_all = pd.read_parquet(source_path).iloc[:, 0]
    else:
        r_all = pd.read_hdf(source_path, key="data")

    years = {}
    for y in range(year_start, year_end + 1):
        idx_name = r_all.index.names[0] if r_all.index.names else "date"
        ym = r_all.index.get_level_values(idx_name).year == y
        if ym.sum() >= 30:
            years[y] = r_all.loc[ym]
            print(f"  年份 {y}: {years[y].shape[0]:,} 行")
    return years


def load_factor_chunked(session_dir: Path, chunk_years=None):
    """
    加载单个因子，支持分年处理以控制内存峰值
    返回: {year: Series} 或 Series
    """
    h5 = session_dir / "result.h5"
    pq = session_dir / "result.parquet"

    if pq.exists():
        fs = pd.read_parquet(pq).iloc[:, 0]
    elif h5.exists():
        fs = pd.read_hdf(h5, key="data").iloc[:, 0]
    else:
        return None

    fs = fs[~fs.index.duplicated(keep="first")]
    fs = fs.ffill().dropna()

    if chunk_years:
        chunks = {}
        for y in chunk_years:
            f_idx_name = fs.index.names[0] if fs.index.names else "date"
            ym = fs.index.get_level_values(f_idx_name).year == y
            if ym.sum() >= 10:
                chunks[y] = fs.loc[ym]
        return chunks
    return fs


# ═══════════════════════════════════════════════
# IC 计算
# ═══════════════════════════════════════════════
def compute_ic_chunked(factor_chunks: dict, returns_chunks: dict) -> tuple:
    """
    分年计算 IC，返回 (全局IC, {year: ic_value})
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

    if not all_f:
        return None, yearly_ic

    global_f = pd.concat(all_f)
    global_r = pd.concat(all_r)
    global_ic = global_f.corr(global_r)
    return global_ic, yearly_ic


def compute_top10(factor_chunks: dict, returns_chunks: dict) -> dict:
    """
    分年计算 Top10 因子组合的中位数收益
    返回: {year: median_return}
    """
    yearly_top10 = {}
    common_years = set(factor_chunks.keys()) & set(returns_chunks.keys())
    for y in sorted(common_years):
        f = factor_chunks[y]
        r = returns_chunks[y]
        common = f.dropna().index.intersection(r.dropna().index)
        if len(common) < 100:
            continue
        fi = f.loc[common]
        ri = r.loc[common]
        decile = fi.rank(pct=True)
        top10_med = ri[decile >= 0.9].median() * 100
        yearly_top10[y] = top10_med
    return yearly_top10


def compute_ic_session(h5: Path, ret_lookup: dict) -> tuple:
    """
    对单个因子 session 计算 IC，返回 (factor_id, {date: ic})
    与 run_ic_fast.py 中的同名函数完全一致
    """
    try:
        df = pd.read_hdf(h5, key="data")
    except Exception:
        return None, {}
    col = df.columns[0]
    s = df[col].copy()
    if s.index.names[0] != "datetime":
        s.index = s.index.set_names(["datetime", "instrument"])
    s = s.reset_index()
    s.columns = ["datetime", "instrument", "factor_val"]
    factor_id = h5.parent.name

    dates = s["datetime"].unique()
    ic_by_date = {}
    for date in dates:
        day = s[s["datetime"] == date]
        vals = day["factor_val"].values.astype(np.float64)
        keys = list(zip(day["datetime"], day["instrument"]))
        rets = np.array([ret_lookup.get(k, np.nan) for k in keys], dtype=np.float64)
        mask = ~(np.isnan(vals) | np.isnan(rets))
        f = vals[mask]
        r = rets[mask]
        if len(f) < 50:
            continue
        rf = rankdata(f)
        rr = rankdata(r)
        n = len(f)
        fc = rf - (n + 1) / 2
        rc = rr - (n + 1) / 2
        denom = np.sqrt(np.sum(fc * fc) * np.sum(rc * rc))
        ic = np.sum(fc * rc) / denom if denom > 1e-15 else np.nan
        ic_by_date[date] = ic

    gc.collect()
    return factor_id, ic_by_date
