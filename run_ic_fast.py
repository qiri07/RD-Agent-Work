#!/usr/bin/env python3
"""
高性能 IC 分析 v5 — 合并对齐 + numpy rankdata
核心思路：将所有因子和收益合并到长表，按日期批量计算 IC
"""
import argparse
import gc
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

pd.set_option('display.max_columns', 20)
pd.set_option('display.width', 200)

import config as cfg

BASE = cfg.PROJECT_ROOT
WS = cfg.RDAGENT_WORKSPACE
SRC_PQ = cfg.DAILY_PV_PQ  # 使用 trade-krono 转换的干净数据
if not SRC_PQ.exists():
    SRC_PQ = cfg.DAILY_PV_FULL_CORRECTED_PQ  # 降级到矫正数据
OUT_DIR = cfg.FACTOR_SOURCE

from feishu_notify import send_combined_report


def main():
    parser = argparse.ArgumentParser(description="高性能 IC 分析 v5")
    parser.add_argument("--feishu-url", default=None, help="飞书 Webhook URL（覆盖环境变量）")
    args = parser.parse_args()

    if args.feishu-url:
        import feishu_notify
        feishu_notify.FEISHU_WEBHOOK_URL = args.feishu-url


def compute_ic_session(h5: Path, ret_lookup: dict) -> tuple:
    """对单个因子 session 计算 IC，返回 (factor_id, {date: ic})"""
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

    # 按日期分组
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


def load_returns_as_long() -> dict:
    """加载价格数据，计算 ret_5d → 字典 {(datetime, instrument): return}"""
    print("加载价格数据...", flush=True)
    t0 = time.time()
    df = pd.read_parquet(SRC_PQ)
    df_reset = df.reset_index()
    df_reset["ret_5d"] = df_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)
    ret_df = df_reset[["date", "instrument", "ret_5d"]].dropna()
    ret_lookup = dict(zip(zip(ret_df["date"], ret_df["instrument"]), ret_df["ret_5d"]))
    n_dates = ret_df["date"].nunique()
    print(f"  {len(ret_lookup):,} 条, {n_dates} 个交易日 ({time.time()-t0:.1f}s)", flush=True)
    return ret_lookup


def compute_ic_long(factors_long: pd.DataFrame, returns_long: pd.DataFrame) -> pd.DataFrame:
    """
    合并后按日期分组，向量化计算 IC
    优化：按日期分块处理，避免一次性合并 695M 行导致 OOM
    """
    print("\n合并数据并计算 IC（分日处理）...", flush=True)
    t_total = time.time()

    # 构建 return lookup: (datetime, instrument) -> return
    ret_lookup = returns_long.set_index(["datetime", "instrument"])["return"].to_dict()
    print(f"  return 字典: {len(ret_lookup):,} 条", flush=True)
    del returns_long
    gc.collect()

    # 按日期分块
    factors_long = factors_long.sort_values(["datetime", "instrument"]).reset_index(drop=True)
    dates = factors_long["datetime"].unique()
    n_dates = len(dates)
    print(f"  {n_dates} 个交易日，开始逐日计算...", flush=True)

    # 预分配结果
    factor_ids = factors_long["factor_id"].unique()
    ic_dict = {fid: [] for fid in factor_ids}

    batch_size = 100
    for bi, date in enumerate(dates):
        day_mask = factors_long["datetime"] == date
        day_data = factors_long[day_mask]
        day_rows = len(day_data)

        # 只保留有对应 return 的行
        keys = list(zip(day_data["datetime"], day_data["instrument"]))
        valid_mask = [k in ret_lookup for k in keys]
        day_matched = day_data[valid_mask]

        # 按因子分组计算 IC
        for fid, grp in day_matched.groupby("factor_id"):
            vals = grp["factor_val"].values.astype(np.float64)
            rets = np.array([ret_lookup[k] for k in zip(grp["datetime"], grp["instrument"])], dtype=np.float64)
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
            print(f"  已处理 {bi+1}/{n_dates} 天 ({day_rows:,} 行/天)...", flush=True)

    print(f"IC 计算完成 ({time.time()-t_total:.1f}s)", flush=True)
    return ic_dict


def summarize(results: dict, factor_ids: list) -> pd.DataFrame:
    """汇总为 DataFrame"""
    rows = []
    for fid in factor_ids:
        ic_list = results.get(fid, [np.nan])
        ic_arr = np.array(ic_list, dtype=np.float64)
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
    print("  因子 IC 分析 (新数据) — v5 分 session 处理版", flush=True)
    print("=" * 70, flush=True)
    t_main = time.time()

    ret_lookup = load_returns_as_long()

    print("加载因子并计算 IC...", flush=True)
    t0 = time.time()
    ic_dict = {}
    session_count = 0
    for d in sorted(WS.iterdir()):
        if not d.is_dir():
            continue
        h5 = d / "result.h5"
        if not h5.exists():
            continue
        try:
            fid, ic_by_date = compute_ic_session(h5, ret_lookup)
            if fid:
                ic_dict[fid] = list(ic_by_date.values())
                session_count += 1
        except Exception as e:
            print(f"  ⚠ {d.name[:8]}: {e}", flush=True)
        if session_count % 10 == 0:
            print(f"  已处理 {session_count} 个因子...", flush=True)

    print(f"  共处理 {session_count} 个因子 ({time.time()-t0:.1f}s)", flush=True)
    del ret_lookup
    gc.collect()

    factor_ids = list(ic_dict.keys())
    ic_df = summarize(ic_dict, factor_ids)

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
