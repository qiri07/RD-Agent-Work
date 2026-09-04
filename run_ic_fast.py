#!/usr/bin/env python3
"""
高性能 IC 分析 v5 — 合并对齐 + numpy rankdata
核心思路：将所有因子和收益合并到长表，按日期批量计算 IC
"""
import gc
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

pd.set_option('display.max_columns', 20)
pd.set_option('display.width', 200)

BASE = Path("/run/media/onai/MyDisk/Work/RD-Agent-Work")
WS = BASE / "git_ignore_folder" / "RD-Agent_workspace"
SRC_PQ = BASE / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv_full.parquet"
OUT_DIR = SRC_PQ.parent

# 导入飞书推送模块
sys.path.insert(0, str(BASE))
from feishu_notify import send_combined_report


def load_factors_as_long() -> pd.DataFrame:
    """加载所有因子 → 长表: [datetime, instrument, factor_id, factor_val]"""
    print("加载因子...", flush=True)
    t0 = time.time()
    rows = []
    for d in sorted(WS.iterdir()):
        if not d.is_dir():
            continue
        h5 = d / "result.h5"
        if not h5.exists():
            continue
        try:
            df = pd.read_hdf(h5, key="data")
            col = df.columns[0]
            s = df[col].copy()
            if s.index.names[0] != "datetime":
                s.index = s.index.set_names(["datetime", "instrument"])
            s = s.reset_index()
            s.columns = ["datetime", "instrument", "factor_val"]
            s["factor_id"] = d.name
            rows.append(s)
        except Exception:
            pass
    long_df = pd.concat(rows, ignore_index=True)
    print(f"  {len(long_df):,} 行 × {long_df['factor_id'].nunique()} 因子 ({time.time()-t0:.1f}s)", flush=True)
    return long_df


def load_returns_as_long() -> pd.DataFrame:
    """加载价格数据，计算 ret_5d → 长表: [date, instrument, return]"""
    print("加载价格数据...", flush=True)
    t0 = time.time()
    df = pd.read_parquet(SRC_PQ)
    df_reset = df.reset_index()
    df_reset["ret_5d"] = df_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)
    ret_df = df_reset[["date", "instrument", "ret_5d"]].dropna()
    ret_df.columns = ["datetime", "instrument", "return"]
    n_dates = ret_df["datetime"].nunique()
    print(f"  {len(ret_df):,} 行, {n_dates} 个交易日 ({time.time()-t0:.1f}s)", flush=True)
    return ret_df


def compute_ic_long(factors_long: pd.DataFrame, returns_long: pd.DataFrame) -> pd.DataFrame:
    """
    合并后按日期分组，向量化计算 IC
    """
    print("\n合并数据并计算 IC...", flush=True)
    t_total = time.time()

    # 合并
    merged = factors_long.merge(returns_long, on=["datetime", "instrument"], how="inner")
    print(f"  合并后: {len(merged):,} 条记录", flush=True)

    # 按日期和因子分组，批量计算 IC
    # 策略：先按日期分块，每天内对每个因子计算 IC
    dates = merged["datetime"].unique()
    n_dates = len(dates)
    print(f"  {n_dates} 个交易日，开始逐日计算...", flush=True)

    # 预分配结果
    factor_ids = factors_long["factor_id"].unique()
    ic_dict = {fid: [] for fid in factor_ids}

    # 构建每日数据字典，按因子分组
    # 更高效的策略：按日期迭代，每天内直接算
    batch_size = 100
    for bi, date in enumerate(dates):
        day_data = merged[merged["datetime"] == date]
        day_groups = day_data.groupby("factor_id")

        for fid, grp in day_groups:
            vals = grp["factor_val"].values.astype(np.float64)
            rets = grp["return"].values.astype(np.float64)
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
            ic_dict[fid].append(ic)

        if (bi + 1) % batch_size == 0:
            print(f"  已处理 {bi+1}/{n_dates} 天...", flush=True)

    # 转数组
    results = {}
    for fid in factor_ids:
        arr = np.array(ic_dict[fid], dtype=np.float64) if ic_dict[fid] else np.array([np.nan])
        results[fid] = arr

    print(f"IC 计算完成 ({time.time()-t_total:.1f}s)", flush=True)
    return results


def summarize(results: dict, factor_ids: list) -> pd.DataFrame:
    """汇总为 DataFrame"""
    rows = []
    for fid in factor_ids:
        ic_arr = results.get(fid, np.array([np.nan]))
        n = len(ic_arr)
        ic_mean = np.nanmean(ic_arr) if n > 0 else np.nan
        ic_std = np.nanstd(ic_arr) if n > 1 else 0.0
        ic_t = ic_mean / (ic_std / np.sqrt(max(n - 1, 1)) + 1e-10) if n > 1 else np.nan
        ic_pos = (ic_arr > 0).mean() if n > 0 else np.nan
        rows.append({
            "factor_id": fid,
            "IC_5d": ic_mean,
            "IC_t_5d": ic_t,
            "IC_pos_5d": ic_pos,
            "n_days": n,
        })
    df = pd.DataFrame(rows).set_index("factor_id")
    df = df.sort_values("IC_5d", key=abs, ascending=False)
    return df


def main():
    print("=" * 70, flush=True)
    print("  因子 IC 分析 (新数据) — v5 合并对齐版", flush=True)
    print("=" * 70, flush=True)
    t_main = time.time()

    factors_long = load_factors_as_long()
    returns_long = load_returns_as_long()

    results = compute_ic_long(factors_long, returns_long)
    factor_ids = factors_long["factor_id"].unique().tolist()
    ic_df = summarize(results, factor_ids)

    # 输出
    ic_out = ic_df.reset_index()
    print(f"\n{'='*70}", flush=True)
    print(f"  IC 汇总结果 (Top 30)", flush=True)
    print(f"{'='*70}", flush=True)
    cols = ["factor_id", "IC_5d", "IC_t_5d", "IC_pos_5d", "n_days"]
    print(ic_out[cols].head(30).to_string(), flush=True)

    print(f"\n{'='*70}", flush=True)
    print(f"  🏆 Top 20 最强因子 (按 |IC_5d|)", flush=True)
    print(f"{'='*70}", flush=True)
    for rank, (_, row) in enumerate(ic_out.head(20).iterrows(), 1):
        print(
            f"  #{rank:2d}  {row['factor_id']:<40s}"
            f"  IC_5d={row['IC_5d']:>+8.4f}"
            f"  t={row['IC_t_5d']:>+7.3f}"
            f"  pos={row['IC_pos_5d']:>+6.3f}"
            f"  n={int(row['n_days'])}",
            flush=True,
        )

    # 保存
    out_pq = OUT_DIR / "ic_scan_results_new.parquet"
    ic_out.to_parquet(out_pq, index=False)
    print(f"\n💾 Parquet: {out_pq}", flush=True)

    out_csv = BASE / "ic_scan_results_new.csv"
    ic_out.to_csv(out_csv, index=False)
    print(f"💾 CSV: {out_csv}", flush=True)

    print(f"\n总耗时: {time.time()-t_main:.1f}s", flush=True)

    # 飞书推送
    try:
        stocks_df = pd.read_csv(BASE / "top10_stocks_new.csv")
        send_combined_report(ic_out, stocks_df, top_n=10)
    except Exception as e:
        print(f"⚠️ 飞书推送失败: {e}", flush=True)


if __name__ == "__main__":
    main()
