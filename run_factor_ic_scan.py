#!/usr/bin/env python3
"""
新数据上重新运行所有因子 + IC 分析，找出最强因子。

用法:
    python3 run_factor_ic_scan.py [--phase1-only] [--phase2-only] [--dry-run]
"""
from __future__ import annotations

import gc
import os
import re
import shutil
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# ── 路径配置 ───────────────────────────────────────────────────────────────────
import config as cfg
BASE = cfg.PROJECT_ROOT
WS = cfg.RDAGENT_WORKSPACE
SRC_H5 = cfg.FACTOR_SOURCE / "daily_pv_full.h5"
SRC_PQ = cfg.FACTOR_SOURCE / "daily_pv_full.parquet"
RETURNS_H5 = cfg.FACTOR_SOURCE / "returns_5d.h5"

PHASE1_ONLY = "--phase1-only" in sys.argv
PHASE2_ONLY = "--phase2-only" in sys.argv
DRY_RUN = "--dry-run" in sys.argv

# IC 分析参数
IC_FORWARD_DAYS = [1, 3, 5]   # 向前收益天数
IC_WINSORIZE = 0.01            # 因子值缩尾处理
IC_MIN_STocks_PER_DAY = 50     # 每日最少股票数


def get_sessions() -> list[Path]:
    return sorted([d for d in WS.iterdir() if d.is_dir() and (d / "factor.py").exists()])


def copy_data_to_session(session: Path) -> bool:
    """将全量数据复制到 session 目录"""
    try:
        dst_h5 = session / "daily_pv.h5"
        dst_pq = session / "daily_pv.parquet"
        if SRC_H5.exists():
            shutil.copy2(SRC_H5, dst_h5)
        if SRC_PQ.exists():
            shutil.copy2(SRC_PQ, dst_pq)
        lock = session / "execution.lock"
        if lock.exists():
            lock.unlink()
        return True
    except Exception as e:
        print(f"  ❌ {session.name}: {e}", flush=True)
        return False


def run_factor(session: Path) -> tuple[bool, str]:
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
        err_msg = str(e)[:200]
        return False, f"❌ {err_msg} ({elapsed:.1f}s)"


def compute_ic(factor_df: pd.Series, returns_df: pd.Series, forward_days: int) -> float:
    """计算因子与 forward returns 的 IC（rank IC）"""
    # 获取日期值（兼容 datetime/date/index level 0）
    f_dates = factor_df.index.get_level_values(0)
    r_dates = returns_df.index.get_level_values(0)

    # 合并：对齐到共同 index
    common_idx = factor_df.index.intersection(returns_df.index)
    if len(common_idx) < 1000:
        return np.nan
    f = factor_df.loc[common_idx]
    r = returns_df.loc[common_idx]

    # 按日期分组，计算每日 rank IC
    daily_ic = pd.Series(index=range(len(f)))
    for dt_val in f_dates.unique():
        mask = f_dates == dt_val
        fg = f[mask]
        rg = r[mask]
        if len(fg) >= IC_MIN_STocks_PER_DAY:
            ic_val = fg.corr(rg, method="spearman")
            if not pd.isna(ic_val):
                daily_ic.loc[mask] = ic_val

    daily_ic = daily_ic.dropna()
    if len(daily_ic) < 10:
        return np.nan
    return daily_ic.mean()


def ic_analysis(factor_results: dict, returns_df: pd.DataFrame) -> pd.DataFrame:
    """对所有因子进行 IC 分析，返回 IC 排名表"""
    print("\n=== IC 分析 ===", flush=True)
    print(f"返回率数据: {returns_df.shape}, 日期范围: {returns_df.index.get_level_values(0).min().date()} ~ {returns_df.index.get_level_values(0).max().date()}", flush=True)

    all_results = []
    total = len(factor_results)

    for i, (factor_id, factor_series) in enumerate(factor_results.items(), 1):
        factor_series = factor_series.copy()
        # 缩尾处理
        if IC_WINSORIZE > 0:
            lower = factor_series.quantile(IC_WINSORIZE)
            upper = factor_series.quantile(1 - IC_WINSORIZE)
            factor_series = factor_series.clip(lower, upper)

        factor_valid = factor_series.dropna()
        if len(factor_valid) < 1000:
            print(f"  [{i}/{total}] {factor_id}: 有效数据不足 ({len(factor_valid)}), 跳过", flush=True)
            continue

        row = {"factor_id": factor_id, "valid_rows": len(factor_valid)}

        for fd in IC_FORWARD_DAYS:
            # 计算 forward return
            fwd_return = returns_df.groupby("instrument")["$close"].pct_change(fd).shift(-fd)
            # 对齐
            common_idx = factor_valid.index.intersection(fwd_return.dropna().index)
            if len(common_idx) < 1000:
                row[f"IC_{fd}d"] = np.nan
                row[f"IC_t_{fd}d"] = np.nan
                row[f"IC_pos_ratio_{fd}d"] = np.nan
                row[f"IC_abs_mean_{fd}d"] = np.nan
                continue

            f = factor_valid.reindex(common_idx)
            r = fwd_return.reindex(common_idx)
            mask = f.notna() & r.notna()
            f, r = f[mask], r[mask]

            ic_val = compute_ic(f, r, fd)
            row[f"IC_{fd}d"] = ic_val

            # t-stat
            if not np.isnan(ic_val) and len(f) > 20:
                std_ic = f.std() / np.sqrt(len(f)) if hasattr(f, 'std') else np.nan
                # 用日度 IC 的 t 统计
                f_dates_tmp = f.index.get_level_values(0)
                r_dates_tmp = r.index.get_level_values(0)
                daily_ic_vals = []
                for dt_val in f_dates_tmp.unique():
                    mask = f_dates_tmp == dt_val
                    fg = f[mask]
                    rg = r[mask]
                    if len(fg) >= IC_MIN_STocks_PER_DAY:
                        ic_v = fg.corr(rg, method="spearman")
                        if not pd.isna(ic_v):
                            daily_ic_vals.append(ic_v)
                daily_ic_tmp = pd.Series(daily_ic_vals)
                if len(daily_ic_tmp) > 1:
                    t_stat = ic_val * np.sqrt(len(daily_ic_tmp) - 2) / np.sqrt(1 - ic_val**2 + 1e-10) if abs(ic_val) < 1 else np.inf
                else:
                    t_stat = np.nan
                row[f"IC_t_{fd}d"] = t_stat
            else:
                row[f"IC_t_{fd}d"] = np.nan

            # IC 为正的比例
            pos_ratio = (daily_ic_tmp > 0).mean() if 'daily_ic_tmp' in dir() else np.nan
            row[f"IC_pos_ratio_{fd}d"] = pos_ratio

            # |IC| 均值
            row[f"IC_abs_mean_{fd}d"] = daily_ic_tmp.abs().mean() if 'daily_ic_tmp' in dir() else np.nan

        all_results.append(row)
        print(f"  [{i}/{total}] {factor_id}: done", flush=True)

    result_df = pd.DataFrame(all_results)

    # 汇总 IC（取各 forward days 的均值）
    ic_cols = [c for c in result_df.columns if c.startswith("IC_") and not c.startswith("IC_t") and not c.startswith("IC_pos") and not c.startswith("IC_abs")]
    if ic_cols:
        result_df["IC_avg"] = result_df[ic_cols].mean(axis=1)
        result_df["IC_abs_avg"] = result_df[[c.replace("IC_", "IC_abs_mean_") for c in ic_cols]].mean(axis=1)

    # 按 |IC_avg| 排序
    result_df = result_df.sort_values("IC_avg", key=abs, ascending=False)

    return result_df


def main():
    print("=" * 70, flush=True)
    print("  新数据因子重算 + IC 分析", flush=True)
    print("=" * 70, flush=True)

    sessions = get_sessions()
    print(f"\n找到 {len(sessions)} 个因子会话", flush=True)
    print(f"源数据: {SRC_H5.stat().st_size/1024/1024:.0f} MB h5, {SRC_PQ.stat().st_size/1024/1024:.0f} MB parquet", flush=True)

    # ── Phase 1: 重算因子 ──────────────────────────────────────────────────────
    if not PHASE2_ONLY:
        print(f"\n━━━ Phase 1: 复制数据 + 重算因子 ━━━", flush=True)
        success, fail = [], []
        for i, s in enumerate(sessions, 1):
            print(f"\n[{i}/{len(sessions)}] {s.name}", end=" ", flush=True)
            # 复制数据
            if not DRY_RUN:
                copy_data_to_session(s)
            # 运行因子
            ok, info = run_factor(s)
            if ok:
                success.append((s.name, info))
                print(info, flush=True)
            else:
                fail.append((s.name, info))
                print(info, flush=True)

        print(f"\nPhase 1 完成: 成功 {len(success)}, 失败 {len(fail)}", flush=True)
        if fail:
            print("失败的因子:", flush=True)
            for name, info in fail:
                print(f"  • {name}: {info}", flush=True)

    # ── Phase 2: IC 分析 ───────────────────────────────────────────────────────
    if not PHASE1_ONLY:
        print(f"\n━━━ Phase 2: IC 分析 ━━━", flush=True)

        # 加载所有 factor 结果
        factor_results = {}
        for s in sessions:
            result_h5 = s / "result.h5"
            result_pq = s / "result.parquet"
            if result_h5.exists():
                try:
                    df = pd.read_hdf(result_h5, key="data")
                    col = df.columns[0]
                    factor_results[s.name] = df[col]
                except Exception as e:
                    print(f"  跳过 {s.name}: {e}", flush=True)
            elif result_pq.exists():
                try:
                    df = pd.read_parquet(result_pq)
                    col = df.columns[0]
                    factor_results[s.name] = df[col]
                except Exception as e:
                    print(f"  跳过 {s.name}: {e}", flush=True)

        print(f"加载了 {len(factor_results)} 个因子结果", flush=True)

        # 加载 forward returns
        print("\n加载收益率数据...", flush=True)
        t0 = time.time()
        fpq = pd.read_parquet(SRC_PQ)
        # parquet index is ['date', 'instrument'], not columns
        fpq_reset = fpq.reset_index()
        fpq_reset["return_5d"] = fpq_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)
        # keep date/instrument columns before subsetting
        returns_df = (
            fpq_reset[["date", "instrument", "$close", "return_5d"]]
            .dropna()
            .set_index(["date", "instrument"])
        )
        returns_df.columns = ["$close", "return"]
        print(f"  收益率数据: {len(returns_df):,} 行, {returns_df.index.get_level_values(0).min().date()} ~ {returns_df.index.get_level_values(0).max().date()} ({time.time()-t0:.1f}s)", flush=True)
        del fpq, fpq_reset
        gc.collect()

        # IC 分析
        ic_df = ic_analysis(factor_results, returns_df)

        # 输出结果
        print(f"\n{'='*70}", flush=True)
        print(f"  IC 分析结果 (按 IC_avg 排序)", flush=True)
        print(f"{'='*70}", flush=True)

        ic_cols_show = [c for c in ic_df.columns if "IC_" in c]
        print(ic_df[["factor_id"] + ic_cols_show].to_string(index=False), flush=True)

        # Top 10
        print(f"\n{'='*70}", flush=True)
        print(f"  🏆 Top 10 最强因子 (按 |IC_avg|)", flush=True)
        print(f"{'='*70}", flush=True)
        top10 = ic_df.head(10)
        for rank, (_, row) in enumerate(top10.iterrows(), 1):
            ic_avg = row.get("IC_avg", np.nan)
            ic_t = row.get("IC_t_5d", np.nan)
            print(f"  #{rank:2d}  {row['factor_id']:<40s}  IC_avg={ic_avg:>+8.4f}  IC_t(5d)={ic_t:>+8.3f}" if not np.isnan(ic_avg) else f"  #{rank:2d}  {row['factor_id']:<40s}  IC_avg=N/A", flush=True)

        # 保存结果
        out_path = cfg.FACTOR_SOURCE / "ic_scan_results.parquet"
        ic_df.to_parquet(out_path)
        print(f"\n💾 IC 分析结果已保存: {out_path}", flush=True)

        # 同时保存 CSV
        csv_path = BASE / "ic_scan_results.csv"
        ic_df.to_csv(csv_path, index=False)
        print(f"💾 CSV 结果已保存: {csv_path}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("完成!", flush=True)


if __name__ == "__main__":
    main()
