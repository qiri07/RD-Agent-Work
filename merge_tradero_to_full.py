#!/usr/bin/env python3
"""
合并 trade-krono-cli 最新数据到 daily_pv_full。

策略：
  - 从 trade-krono-cli 读取全量 K 线，转换为 RD-Agent 格式并去重（每日 per instrument 保留一条）
  - 与现有 daily_pv_full.parquet 合并：
      * 历史数据（2018-01-02 ~ 2022-08-30）保留
      * trade-krono 的新增股票（不在 full 中）追加
      * trade-krono 的已有股票（在 full 中）用 trade-krono 数据覆盖（获取最新值）
  - 输出覆盖 daily_pv_full.{parquet,h5}，并重建 returns_5d.h5
  - Debug 目录同步更新（前 100 只股票）
"""

import io
import os
import sqlite3
import subprocess
from pathlib import Path

import pandas as pd

# ── 路径配置 ──
BASE = Path(__file__).parent
TRADERO_CACHE_DB = Path(
    "/run/media/onai/MyDisk/Work/trade-krono-cli/outputs/cache/pipeline_cache.db"
)
OUT_DIR_MAIN = BASE / "git_ignore_folder" / "factor_implementation_source_data"
OUT_DIR_DEBUG = BASE / "git_ignore_folder" / "factor_implementation_source_data_debug"

PARQUET_FULL = OUT_DIR_MAIN / "daily_pv_full.parquet"
H5_FULL = OUT_DIR_MAIN / "daily_pv_full.h5"
PARQUET_DEBUG = OUT_DIR_DEBUG / "daily_pv.parquet"
H5_DEBUG = OUT_DIR_DEBUG / "daily_pv.h5"
RETURNS_H5 = OUT_DIR_MAIN / "returns_5d.h5"


def ticker_to_qlib(ticker: str) -> str:
    return ticker.replace(".", "").upper()


def load_tradero_data() -> pd.DataFrame:
    """从 trade-krono-cli 缓存读取全量数据，转换为 RD-Agent 格式并去重"""
    print(f"读取 trade-krono-cli 缓存: {TRADERO_CACHE_DB}", flush=True)
    conn = sqlite3.connect(str(TRADERO_CACHE_DB))
    total = conn.execute("SELECT COUNT(*) FROM kline_cache").fetchone()[0]
    print(f"总 tickers: {total}", flush=True)

    rows = []
    cursor = conn.execute("SELECT ticker, data FROM kline_cache")
    for i, (ticker, blob) in enumerate(cursor, 1):
        df = pd.read_pickle(io.BytesIO(blob))
        df["instrument"] = ticker_to_qlib(ticker)
        rows.append(df)
        if i % 2000 == 0:
            print(f"  已读取 {i}/{total} 只股票...", flush=True)
    conn.close()

    combined = pd.concat(rows, ignore_index=True)
    print(f"trade-krono 原始: {len(combined):,} 行, {combined['instrument'].nunique()} 只", flush=True)
    return combined


def convert(df: pd.DataFrame) -> pd.DataFrame:
    """转换为 RD-Agent 格式并去重（每日 per instrument 保留一行，volume > 0 优先）"""
    print("转换格式...", flush=True)
    df = df.copy()
    df["date"] = pd.to_datetime(df["timestamps"]).dt.normalize()
    df = df.rename(columns={
        "open": "$open", "high": "$high", "low": "$low",
        "close": "$close", "volume": "$volume",
    })
    df["$factor"] = 1.0
    df = df.dropna(subset=["$open", "$close", "$volume"])
    df = df[df["$high"] > 0]

    # 去重：同一 date+instrument 可能有多条（trade-krono 数据源问题）
    # 策略：优先保留 $volume > 0 且 $volume >= 1 的记录
    df = df.sort_values("$volume", ascending=False)
    df = df.drop_duplicates(subset=["date", "instrument"], keep="first")

    df = df.set_index(["date", "instrument"]).sort_index()
    df.index.names = ["date", "instrument"]
    df = df[["$open", "$close", "$high", "$low", "$volume", "$factor"]]
    return df


def load_existing_full() -> pd.DataFrame | None:
    """加载现有 daily_pv_full.parquet"""
    if not PARQUET_FULL.exists():
        return None
    df = pd.read_parquet(PARQUET_FULL)
    print(f"现有 full 数据: {len(df):,} 行, {df.index.get_level_values('instrument').nunique()} 只, "
          f"{df.index.get_level_values('date').min().date()} ~ {df.index.get_level_values('date').max().date()}", flush=True)
    return df


def merge_data(existing: pd.DataFrame, tradero: pd.DataFrame) -> pd.DataFrame:
    """
    合并策略：
    - 历史部分（existing 中有、tradero 中没有的股票）保留
    - tradero 中的股票（无论是否已有）用 tradero 数据（获取最新完整序列）
    - 即：tradero 数据优先，existing 仅补充 tradero 中没有的股票
    """
    print("合并数据...", flush=True)
    existing_insts = set(existing.index.get_level_values("instrument").unique())
    tradero_insts = set(tradero.index.get_level_values("instrument").unique())

    new_insts = tradero_insts - existing_insts
    overlap_insts = tradero_insts & existing_insts

    print(f"  tradero 新股票: {len(new_insts)}", flush=True)
    print(f"  tradero 重叠股票: {len(overlap_insts)}", flush=True)
    print(f"  existing 独有股票: {len(existing_insts - tradero_insts)}", flush=True)

    # 保留 existing 中 tradero 没有的股票
    existing_only = existing[
        ~existing.index.get_level_values("instrument").isin(tradero_insts)
    ]
    print(f"  existing-only 行数: {len(existing_only):,}", flush=True)

    # 合并
    merged = pd.concat([existing_only.reset_index(), tradero.reset_index()]).set_index(
        ["date", "instrument"]
    ).sort_index()

    print(f"  合并后: {len(merged):,} 行, {merged.index.get_level_values('instrument').nunique()} 只", flush=True)
    print(f"  日期范围: {merged.index.get_level_values('date').min().date()} ~ {merged.index.get_level_values('date').max().date()}", flush=True)
    return merged


def save_parquet_h5(df: pd.DataFrame, parquet_path: Path, h5_path: Path):
    """保存 parquet 和 h5"""
    print(f"\n保存 {parquet_path.name}...", flush=True)
    df.to_parquet(str(parquet_path), engine="pyarrow")
    size_pq = parquet_path.stat().st_size / 1024 / 1024
    print(f"  parquet: {size_pq:.1f} MB", flush=True)

    env_py = Path(__file__).parent / "rdagent-env" / "bin" / "python"
    if env_py.exists():
        result = subprocess.run(
            [str(env_py), "-c",
             f"import pandas as pd; "
             f"df=pd.read_parquet('{parquet_path}'); "
             f"df.to_hdf('{h5_path}', key='data', mode='w')"],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode == 0:
            size_h5 = h5_path.stat().st_size / 1024 / 1024
            print(f"  h5:      {size_h5:.1f} MB", flush=True)
        else:
            print(f"  h5 保存失败: {result.stderr}", flush=True)
    else:
        print(f"  h5 跳过: 未找到 rdagent-env/python", flush=True)


def save_debug(df: pd.DataFrame):
    """保存 debug 数据（前 100 只股票）"""
    debug_insts = df.index.get_level_values("instrument").unique()[:100]
    debug_df = df.loc[pd.IndexSlice[:, debug_insts], :]
    print(f"\n保存 debug 数据: {len(debug_df):,} 行, {debug_df.index.get_level_values('instrument').nunique()} 只", flush=True)
    save_parquet_h5(debug_df, PARQUET_DEBUG, H5_DEBUG)


def regenerate_returns(df: pd.DataFrame):
    """从 full 数据重新生成 returns_5d.h5"""
    print("\n重建 returns_5d.h5...", flush=True)
    df_work = df.reset_index()
    df_work["return_5d"] = df_work.groupby("instrument")["$close"].pct_change(5)
    df_ret = df_work.dropna(subset=["return_5d"]).copy()
    df_ret = df_ret[["date", "instrument", "return_5d"]].set_index(["date", "instrument"])
    df_ret.columns = ["return_5d"]

    df_ret.to_hdf(str(RETURNS_H5), key="returns", mode="w", format="table")
    size = RETURNS_H5.stat().st_size / 1024 / 1024
    dates = df_ret.index.get_level_values(0)
    print(f"  returns_5d.h5: {size:.1f} MB, {len(df_ret):,} 条目, "
          f"{dates.min().date()} ~ {dates.max().date()}", flush=True)


def main():
    print("=" * 60, flush=True)
    print("trade-krono-cli → daily_pv_full 合并转换", flush=True)
    print("=" * 60, flush=True)

    # 1. 加载 trade-krono 数据
    tradero_raw = load_tradero_data()

    # 2. 转换并去重
    tradero = convert(tradero_raw)
    tr_dates = tradero.index.get_level_values("date")
    print(f"trade-krono 转换后: {len(tradero):,} 行, {tradero.index.get_level_values('instrument').nunique()} 只, "
          f"{tr_dates.min().date()} ~ {tr_dates.max().date()}", flush=True)

    # 3. 加载现有 full 数据
    existing = load_existing_full()

    # 4. 合并
    if existing is not None:
        merged = merge_data(existing, tradero)
    else:
        merged = tradero
        print("无已有数据，直接使用 trade-krono 数据", flush=True)

    # 5. 保存 full 数据
    save_parquet_h5(merged, PARQUET_FULL, H5_FULL)

    # 6. 保存 debug 数据
    save_debug(merged)

    # 7. 重建 returns_5d
    regenerate_returns(merged)

    print(f"\n{'='*60}", flush=True)
    print("=== Done! ===", flush=True)
    print(f"全量数据: {len(merged):,} 行, {merged.index.get_level_values('instrument').nunique()} 只", flush=True)
    print(f"日期范围: {merged.index.get_level_values('date').min().date()} ~ {merged.index.get_level_values('date').max().date()}", flush=True)
    print(f"Latest date rows: {(merged.index.get_level_values('date') == merged.index.get_level_values('date').max()).sum()}", flush=True)


if __name__ == "__main__":
    main()
