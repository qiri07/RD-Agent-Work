#!/usr/bin/env python3
"""
因子 IC 分析引擎模块
====================
从 run_factor_ic_scan.py 提取的公共逻辑。
提供 compute_ic、ic_analysis 等核心 IC 计算功能。
"""
from __future__ import annotations

import gc
import time
from typing import Dict

import numpy as np
import pandas as pd


# IC 分析参数
IC_FORWARD_DAYS = [1, 3, 5]   # 向前收益天数
IC_WINSORIZE = 0.01            # 因子值缩尾处理
IC_MIN_STocks_PER_DAY = 50     # 每日最少股票数


def compute_ic(factor_df: pd.Series, returns_df: pd.Series,
               forward_days: int = 5) -> float:
    """计算因子与 forward returns 的 IC（rank IC）

    Args:
        factor_df: 因子值序列 (MultiIndex: datetime, instrument)
        returns_df: 收益率序列 (MultiIndex: datetime, instrument)
        forward_days: 向前收益天数

    Returns:
        日度 IC 均值，数据不足返回 nan
    """
    f_dates = factor_df.index.get_level_values(0)
    r_dates = returns_df.index.get_level_values(0)

    common_idx = factor_df.index.intersection(returns_df.index)
    if len(common_idx) < 1000:
        return np.nan

    f = factor_df.loc[common_idx]
    r = returns_df.loc[common_idx]

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


def ic_analysis(factor_results: Dict[str, pd.Series],
                returns_df: pd.DataFrame) -> pd.DataFrame:
    """对所有因子进行 IC 分析，返回 IC 排名表

    Args:
        factor_results: {factor_id: factor_series}
        returns_df: 包含 ['$close', 'return'] 列的 DataFrame

    Returns:
        IC 排名 DataFrame
    """
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
            print(f"  [{i}/{total}] {factor_id}: 有效数据不足 ({len(factor_valid)}), 跳过")
            continue

        row = {"factor_id": factor_id, "valid_rows": len(factor_valid)}

        for fd in IC_FORWARD_DAYS:
            fwd_return = returns_df.groupby("instrument")["$close"].pct_change(fd).shift(-fd)
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
                f_dates_tmp = f.index.get_level_values(0)
                r_dates_tmp = r.index.get_level_values(0)
                daily_ic_vals = []
                for dt_val in f_dates_tmp.unique():
                    m = f_dates_tmp == dt_val
                    fg = f[m]
                    rg = r[m]
                    if len(fg) >= IC_MIN_STocks_PER_DAY:
                        ic_v = fg.corr(rg, method="spearman")
                        if not pd.isna(ic_v):
                            daily_ic_vals.append(ic_v)
                daily_ic_tmp = pd.Series(daily_ic_vals)
                if len(daily_ic_tmp) > 1:
                    t_stat = (ic_val * np.sqrt(len(daily_ic_tmp) - 2)
                              / np.sqrt(1 - ic_val**2 + 1e-10)
                              if abs(ic_val) < 1 else np.inf)
                else:
                    t_stat = np.nan
                row[f"IC_t_{fd}d"] = t_stat
            else:
                row[f"IC_t_{fd}d"] = np.nan

            # IC 为正的比例
            pos_ratio = (daily_ic_tmp > 0).mean() if 'daily_ic_tmp' in dir() else np.nan
            row[f"IC_pos_ratio_{fd}d"] = pos_ratio
            row[f"IC_abs_mean_{fd}d"] = daily_ic_tmp.abs().mean() if 'daily_ic_tmp' in dir() else np.nan

        all_results.append(row)
        print(f"  [{i}/{total}] {factor_id}: done")

    result_df = pd.DataFrame(all_results)

    # 汇总 IC（取各 forward days 的均值）
    ic_cols = [c for c in result_df.columns
               if c.startswith("IC_") and not c.startswith("IC_t")
               and not c.startswith("IC_pos") and not c.startswith("IC_abs")]
    if ic_cols:
        result_df["IC_avg"] = result_df[ic_cols].mean(axis=1)
        result_df["IC_abs_avg"] = result_df[
            [c.replace("IC_", "IC_abs_mean_") for c in ic_cols]
        ].mean(axis=1)

    # 按 |IC_avg| 排序
    result_df = result_df.sort_values("IC_avg", key=abs, ascending=False)
    return result_df


def run_ic_scan(sessions=None, phase1_only: bool = False,
                phase2_only: bool = False, dry_run: bool = False) -> pd.DataFrame:
    """运行完整的 IC 扫描流程（因子重算 + IC分析）

    Args:
        sessions: 因子会话列表（None=从 workspace 自动发现）
        phase1_only: 只运行 Phase 1（因子重算）
        phase2_only: 只运行 Phase 2（IC分析）
        dry_run: 只复制数据不重算

    Returns:
        IC 分析 DataFrame
    """
    from batch_recompute_factors import get_sessions, copy_data_to_session, recompute_factor as run_factor

    if sessions is None:
        sessions = get_sessions()

    print(f"\n找到 {len(sessions)} 个因子会话", flush=True)

    # Phase 1: 重算因子
    if not phase2_only:
        print(f"\n━━━ Phase 1: 复制数据 + 重算因子 ━━━", flush=True)
        success, fail = [], []
        for i, s in enumerate(sessions, 1):
            print(f"\n[{i}/{len(sessions)}] {s.name}", end=" ", flush=True)
            if not dry_run:
                copy_data_to_session(s)
            ok, info = run_factor(s)
            if ok:
                success.append((s.name, info))
                print(info, flush=True)
            else:
                fail.append((s.name, info))
                print(info, flush=True)
        print(f"\nPhase 1 完成: 成功 {len(success)}, 失败 {len(fail)}", flush=True)

    # Phase 2: IC 分析
    if not phase1_only:
        print(f"\n━━━ Phase 2: IC 分析 ━━━", flush=True)
        factor_results = {}
        for s in sessions:
            result_h5 = s / "result.h5"
            result_pq = s / "result.parquet"
            if result_h5.exists():
                try:
                    df = pd.read_hdf(result_h5, key="data")
                    factor_results[s.name] = df[df.columns[0]]
                except Exception as e:
                    print(f"  跳过 {s.name}: {e}", flush=True)
            elif result_pq.exists():
                try:
                    df = pd.read_parquet(result_pq)
                    factor_results[s.name] = df[df.columns[0]]
                except Exception as e:
                    print(f"  跳过 {s.name}: {e}", flush=True)

        print(f"加载了 {len(factor_results)} 个因子结果", flush=True)

        # 加载 forward returns
        src_pq = __import__('config', fromlist=['FACTOR_SOURCE']).cfg.FACTOR_SOURCE / "daily_pv_full.parquet"
        t0 = time.time()
        fpq = pd.read_parquet(src_pq)
        fpq_reset = fpq.reset_index()
        fpq_reset["return_5d"] = fpq_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)
        returns_df = (
            fpq_reset[["date", "instrument", "$close", "return_5d"]]
            .dropna()
            .set_index(["date", "instrument"])
        )
        returns_df.columns = ["$close", "return"]
        print(f"  收益率数据: {len(returns_df):,} 行 ({time.time()-t0:.1f}s)", flush=True)
        del fpq, fpq_reset
        gc.collect()

        ic_df = ic_analysis(factor_results, returns_df)

        # 输出结果
        print(f"\n{'='*70}", flush=True)
        print(f"  IC 分析结果 (按 IC_avg 排序)", flush=True)
        print(f"{'='*70}", flush=True)
        ic_cols_show = [c for c in ic_df.columns if "IC_" in c]
        print(ic_df[["factor_id"] + ic_cols_show].to_string(index=False), flush=True)

        # 保存
        out_pq = src_pq.parent / "ic_scan_results.parquet"
        ic_df.to_parquet(out_pq)
        out_csv = src_pq.parent.parent / "ic_scan_results.csv"
        ic_df.to_csv(out_csv, index=False)
        print(f"\n结果已保存: {out_pq}, {out_csv}", flush=True)

        return ic_df

    return None
