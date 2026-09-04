#!/usr/bin/env python3
"""
Download fresh A-share daily data from baostock and save as parquet.
Usage: python3 download_astock_data.py [num_stocks] [start_date] [end_date]
"""

import sys
import time
from pathlib import Path

import baostock as bs
import pandas as pd

BASE_DIR = Path(__file__).parent
MAIN_DATA_PATH = BASE_DIR / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv.parquet"
DEBUG_DATA_PATH = BASE_DIR / "git_ignore_folder" / "factor_implementation_source_data_debug" / "daily_pv.parquet"

MAX_STOCKS = int(sys.argv[1]) if len(sys.argv) > 1 else 500
START_DATE = sys.argv[2] if len(sys.argv) > 2 else "2018-01-01"
END_DATE = sys.argv[3] if len(sys.argv) > 3 else "2026-08-31"


def main():
    print(f"=== A股数据下载 ===", flush=True)
    print(f"Stocks: {MAX_STOCKS}, Range: {START_DATE} ~ {END_DATE}", flush=True)

    # Login once and keep open
    lg = bs.login()
    if lg.error_code != "0":
        print(f"Login failed: {lg.error_msg}", flush=True)
        sys.exit(1)
    print("login success!", flush=True)

    # Get stock list
    rs = bs.query_stock_basic()
    stocks = []
    while (rs.error_code == "0") & rs.next():
        row = rs.get_row_data()
        code = row[0]
        if code.startswith("sh.6") or code.startswith("sz.0") or code.startswith("sz.3"):
            qlib_code = code.replace(".", "").upper()
            stocks.append((code, qlib_code))
        if len(stocks) >= MAX_STOCKS:
            break
    print(f"Found {len(stocks)} A-share stocks", flush=True)

    # Download all data
    print(f"\nDownloading...", flush=True)
    all_rows = []
    t0 = time.time()

    for i, (bs_code, qlib_code) in enumerate(stocks):
        rs2 = bs.query_history_k_data_plus(
            bs_code, "date,code,open,high,low,close,volume",
            start_date=START_DATE, end_date=END_DATE,
            frequency="d", adjustflag="2",
        )
        while (rs2.error_code == "0") & rs2.next():
            r = rs2.get_row_data()
            all_rows.append({
                "date": r[0], "instrument": qlib_code,
                "open": float(r[2]) if r[2] else None,
                "high": float(r[3]) if r[3] else None,
                "low": float(r[4]) if r[4] else None,
                "close": float(r[5]) if r[5] else None,
                "volume": float(r[6]) if r[6] else None,
            })
        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"  {i+1}/{len(stocks)} ({(i+1)*100//len(stocks)}%) | {elapsed:.0f}s elapsed", flush=True)

    bs.logout()
    print(f"Downloaded {len(all_rows)} rows in {time.time()-t0:.1f}s", flush=True)

    if len(all_rows) == 0:
        print("No data!", flush=True)
        return

    # Build DataFrame
    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["open", "close", "volume"])
    df = df[df["high"] > 0]

    # Set MultiIndex
    df = df.set_index(["date", "instrument"]).sort_index()
    df.columns = ["$open", "$high", "$low", "$close", "$volume"]
    df = df[["$open", "$close", "$high", "$low", "$volume"]]
    df["$factor"] = 1.0
    df = df[["$open", "$close", "$high", "$low", "$volume", "$factor"]]

    print(f"Final: {df.shape[0]} rows, {df.index.get_level_values('instrument').nunique()} stocks", flush=True)
    print(f"Date range: {df.index.get_level_values('date').min()} ~ {df.index.get_level_values('date').max()}", flush=True)

    # Save as parquet
    MAIN_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(str(MAIN_DATA_PATH), engine="pyarrow")
    print(f"Saved main: {MAIN_DATA_PATH} ({MAIN_DATA_PATH.stat().st_size/1024/1024:.1f} MB)", flush=True)

    # Debug: first 100 stocks
    debug_insts = df.index.get_level_values("instrument").unique()[:100]
    debug_df = df.loc[pd.IndexSlice[:, debug_insts], :]
    DEBUG_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    debug_df.to_parquet(str(DEBUG_DATA_PATH), engine="pyarrow")
    print(f"Saved debug: {DEBUG_DATA_PATH} ({DEBUG_DATA_PATH.stat().st_size/1024/1024:.1f} MB)", flush=True)

    print("\n=== Done! ===", flush=True)


if __name__ == "__main__":
    main()
