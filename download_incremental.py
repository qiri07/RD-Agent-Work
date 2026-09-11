#!/usr/bin/env python3
"""
增量下载最近缺失的交易日数据（只下载最近几天，快很多）
从 daily_pv_full.parquet 已有的最新日期开始，补全到今天。
"""
import sys
import time
from pathlib import Path
from datetime import date, datetime, timedelta

import pandas as pd
import baostock as bs

BASE = Path(__file__).parent
SRC_PQ = BASE / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv_full.parquet"
DST_PQ = SRC_PQ  # 直接覆盖更新

MAX_STOCKS = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
SLEEP = 0.15

def main():
    if not SRC_PQ.exists():
        print(f"❌ 源文件不存在: {SRC_PQ}")
        return

    # 读取现有数据
    df = pd.read_parquet(SRC_PQ)
    idx = df.index
    latest_date = idx.get_level_values("date").max()
    today = date.today()
    n_stocks = idx.get_level_values("instrument").nunique()
    print(f"现有数据: {len(df):,} 行, {n_stocks} 只股票")
    print(f"最新日期: {latest_date.date()}")
    print(f"今天:     {today}")

    if latest_date.date() >= today:
        print("✅ 数据已是最新，无需下载")
        return

    # 计算需要下载的日期范围
    dates_to_download = []
    d = latest_date.date() + timedelta(days=1)
    while d <= today:
        dates_to_download.append(d)
        d += timedelta(days=1)

    print(f"需下载 {len(dates_to_download)} 个交易日: {dates_to_download[0]} ~ {dates_to_download[-1]}")

    # 获取股票列表（从现有数据）
    stocks = idx.get_level_values("instrument").unique().tolist()
    stocks = stocks[:MAX_STOCKS]
    print(f"股票数: {len(stocks)}")

    # 登录 baostock
    lg = bs.login()
    if lg.error_code != "0":
        print(f"登录失败: {lg.error_msg}")
        return
    print("baostock login OK")

    new_rows = []
    t0 = time.time()

    for i, code in enumerate(stocks, 1):
        bs_code = code.lower().replace("bj", "sh.") if code.startswith("bj") else (
            "sh." + code[2:] if code.startswith("SH") or code.startswith("sh6") else
            "sz." + code[2:] if code.startswith("SZ") or code.startswith("sz0") or code.startswith("sz3") else None
        )
        if not bs_code:
            continue

        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,volume",
                start_date=dates_to_download[0].isoformat(),
                end_date=dates_to_download[-1].isoformat(),
                frequency="d", adjustflag="2",
            )
            count = 0
            while (rs.error_code == "0") & rs.next():
                r = rs.get_row_data()
                try:
                    new_rows.append({
                        "instrument": code,
                        "date": pd.to_datetime(r[0]),
                        "$open": float(r[2]) if r[2] else None,
                        "$close": float(r[3]) if r[4] else None,
                        "$high": float(r[4]) if r[4] else None,
                        "$low": float(r[5]) if r[5] else None,
                        "$volume": float(r[6]) if r[6] else None,
                        "$factor": 1.0,
                    })
                    count += 1
                except Exception:
                    pass
        except Exception as e:
            pass  # 跳过异常股票

        if i % 200 == 0:
            elapsed = time.time() - t0
            print(f"  {i}/{len(stocks)} ({i*100//len(stocks)}%) | {elapsed:.0f}s | 新增 {len(new_rows):,} 行", flush=True)

        time.sleep(SLEEP)

    bs.logout()

    if not new_rows:
        print("没有新数据")
        return

    new_df = pd.DataFrame(new_rows)
    new_df = new_df.dropna(subset=["$open", "$close", "$volume"])
    new_df = new_df[new_df["$high"] > 0]
    new_df["date"] = pd.to_datetime(new_df["date"])
    new_df = new_df.set_index(["date", "instrument"]).sort_index()

    # 合并到现有数据
    df_reset = df.reset_index()
    combined = pd.concat([df_reset, new_df.reset_index()], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "instrument"], keep="last")
    combined = combined.sort_values(["instrument", "date"]).reset_index(drop=True)
    combined = combined.set_index(["date", "instrument"])

    for c in ["$open", "$close", "$high", "$low", "$volume", "$factor"]:
        if c not in combined.columns:
            combined[c] = 1.0 if c == "$factor" else 0.0
    combined = combined[["$open", "$close", "$high", "$low", "$volume", "$factor"]]

    combined.to_parquet(DST_PQ, engine="pyarrow")
    new_dates = combined.index.get_level_values("date").unique()
    print(f"\n✅ 完成! {len(combined):,} 行, {combined.index.get_level_values('instrument').nunique()} 只")
    print(f"日期范围: {new_dates.min().date()} ~ {new_dates.max().date()}")
    print(f"耗时: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
