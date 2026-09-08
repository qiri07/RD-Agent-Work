#!/usr/bin/env python3
"""
高性能 IC 分析 v5 — 分 session 逐因子处理，避免 OOM
核心思路：逐个 session 加载因子，与预计算的返回字典计算 IC
"""
import argparse
import gc
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option('display.max_columns', 20)
pd.set_option('display.width', 200)

import config as cfg
from ic_compute import compute_ic_session

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

    print("=" * 70, flush=True)
    print("  因子 IC 分析 (新数据) — v5 分 session 处理版", flush=True)
    print("=" * 70, flush=True)
    t_main = time.time()

    # Step 1: 加载价格数据，计算 forward returns → 字典
    print("加载价格数据...", flush=True)
    t0 = time.time()
    df = pd.read_parquet(SRC_PQ)
    df_reset = df.reset_index()
    df_reset["ret_5d"] = df_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)
    ret_df = df_reset[["date", "instrument", "ret_5d"]].dropna()
    ret_lookup = dict(zip(zip(ret_df["date"], ret_df["instrument"]), ret_df["ret_5d"]))
    n_dates = ret_df["date"].nunique()
    print(f"  {len(ret_lookup):,} 条, {n_dates} 个交易日 ({time.time()-t0:.1f}s)", flush=True)

    # Step 2: 逐 session 计算 IC
    print("\n加载因子并计算 IC...", flush=True)
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

    # Step 3: 汇总排名
    rows = []
    for fid, ic_list in ic_dict.items():
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
    ic_df = pd.DataFrame(rows).set_index("factor_id")
    ic_df = ic_df.sort_values("IC_5d", key=abs, ascending=False)
    ic_out = ic_df.reset_index()

    # 输出
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
    sys.exit(main())
