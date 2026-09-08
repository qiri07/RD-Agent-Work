#!/usr/bin/env python3
"""
将 trade-krono-cli 缓存的 K 线数据转换为 RD-Agent daily_pv 格式。
同时合并已有数据（保留更早的历史），覆盖输出到两个位置：
  - factor_implementation_source_data/daily_pv.{parquet,h5}
  - factor_implementation_source_data_debug/daily_pv.{parquet,h5}
"""

import io
import sqlite3
from pathlib import Path

import pandas as pd

# ── 路径配置 ──
import os as _os
BASE = Path(__file__).parent
TRADERO_CACHE_DB = Path(
    _os.getenv("TRADERO_CACHE_DB", "/run/media/onai/MyDisk/Work/trade-krono-cli/outputs/cache/pipeline_cache.db")
)
OUT_DIR_MAIN = BASE / "git_ignore_folder" / "factor_implementation_source_data"
OUT_DIR_DEBUG = BASE / "git_ignore_folder" / "factor_implementation_source_data_debug"

PARQUET_MAIN = OUT_DIR_MAIN / "daily_pv.parquet"
H5_MAIN = OUT_DIR_MAIN / "daily_pv.h5"
PARQUET_DEBUG = OUT_DIR_DEBUG / "daily_pv.parquet"
H5_DEBUG = OUT_DIR_DEBUG / "daily_pv.h5"

# ── ticker 格式转换：sh.600519 -> SH600519 ──
def ticker_to_qlib(ticker: str) -> str:
    return ticker.replace(".", "").upper()


def load_tradero_data() -> pd.DataFrame:
    """从 trade-krono-cli 的 kline_cache 读取全量数据"""
    print(f"读取 trade-krono-cli 缓存: {TRADERO_CACHE_DB}", flush=True)
    conn = sqlite3.connect(str(TRADERO_CACHE_DB))
    cursor = conn.execute("SELECT ticker, data FROM kline_cache")
    rows = []
    total = conn.execute("SELECT COUNT(*) FROM kline_cache").fetchone()[0]
    for i, (ticker, blob) in enumerate(cursor, 1):
        df = pd.read_pickle(io.BytesIO(blob))
        df["instrument"] = ticker_to_qlib(ticker)
        rows.append(df)
        if i % 1000 == 0:
            print(f"  已读取 {i}/{total} 只股票...", flush=True)
    conn.close()

    combined = pd.concat(rows, ignore_index=True)
    print(f"trade-krono 原始: {len(combined):,} 行, {combined['instrument'].nunique()} 只", flush=True)
    return combined


def load_existing() -> pd.DataFrame | None:
    """加载已有的 daily_pv.parquet（若有）"""
    if not PARQUET_MAIN.exists():
        return None
    df = pd.read_parquet(PARQUET_MAIN)
    print(f"已有数据: {len(df):,} 行, {df.index.get_level_values('instrument').nunique()} 只", flush=True)
    return df


def convert(df: pd.DataFrame) -> pd.DataFrame:
    """将 trade-krono 格式转为 RD-Agent 格式"""
    df = df.copy()
    df["date"] = pd.to_datetime(df["timestamps"]).dt.normalize()
    df = df.rename(columns={
        "open": "$open",
        "high": "$high",
        "low": "$low",
        "close": "$close",
        "volume": "$volume",
    })
    df["$factor"] = 1.0
    df = df.dropna(subset=["$open", "$close", "$volume"])
    df = df[df["$high"] > 0]
    # 先设索引，再只保留需要的列
    df = df.set_index(["date", "instrument"]).sort_index()
    df.index.names = ["date", "instrument"]
    df = df[["$open", "$close", "$high", "$low", "$volume", "$factor"]]
    return df


def save(df: pd.DataFrame, parquet_path: Path, h5_path: Path):
    df.to_parquet(str(parquet_path), engine="pyarrow")
    print(f"  parquet: {parquet_path} ({parquet_path.stat().st_size / 1024 / 1024:.1f} MB)", flush=True)
    # 用 rdagent-env 的 Python 保存 h5（系统 Python 无 pytables）
    import subprocess
    env_py = Path(__file__).parent / "rdagent-env" / "bin" / "python"
    if env_py.exists():
        result = subprocess.run(
            [str(env_py), "-c",
             f"import pandas as pd; "
             f"df=pd.read_parquet('{parquet_path}'); "
             f"df.to_hdf('{h5_path}', key='data', mode='w')"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            print(f"  h5:      {h5_path} ({h5_path.stat().st_size / 1024 / 1024:.1f} MB)", flush=True)
        else:
            print(f"  h5 保存失败: {result.stderr}", flush=True)
    else:
        print(f"  h5 跳过: 未找到 rdagent-env/python", flush=True)


def main():
    # 1. 加载 trade-krono 数据
    tradero_df = load_tradero_data()
    tradero_converted = convert(tradero_df)
    print(f"trade-krono 转换后: {len(tradero_converted):,} 行, "
          f"{tradero_converted.index.get_level_values('instrument').nunique()} 只, "
          f"{tradero_converted.index.get_level_values('date').min()} ~ "
          f"{tradero_converted.index.get_level_values('date').max()}", flush=True)

    # 2. 合并已有数据（保留更早历史）
    existing = load_existing()
    if existing is not None:
        existing_insts = set(existing.index.get_level_values("instrument").unique())
        new_insts = set(tradero_converted.index.get_level_values("instrument").unique())
        # 如果已有数据已经包含全部 trade-krono 股票，直接跳过合并
        if new_insts <= existing_insts:
            print("已有数据已包含全部 trade-krono 股票，跳过合并", flush=True)
            merged = existing
        else:
            overlap = existing_insts & new_insts
            if overlap:
                tradero_clean = tradero_converted[
                    ~tradero_converted.index.get_level_values("instrument").isin(overlap)
                ]
                existing_clean = existing[
                    ~existing.index.get_level_values("instrument").isin(overlap)
                ]
                merged = pd.concat([
                    existing_clean.reset_index(),
                    tradero_clean.reset_index(),
                ]).set_index(["date", "instrument"]).sort_index()
                # 去重：同一(date, instrument)只保留首次出现的行
                merged = merged[~merged.index.duplicated(keep='first')]
            else:
                merged = pd.concat([
                    existing.reset_index(),
                    tradero_converted.reset_index(),
                ]).set_index(["date", "instrument"]).sort_index()
                # 去重：同一(date, instrument)只保留首次出现的行
                merged = merged[~merged.index.duplicated(keep='first')]
            print(f"合并后: {len(merged):,} 行, {merged.index.get_level_values('instrument').nunique()} 只", flush=True)
    else:
        merged = tradero_converted
        print("无已有数据，直接使用 trade-krono 数据", flush=True)

    # 3. 保存
    print("\n保存数据...", flush=True)
    # main: 全量
    save(merged, PARQUET_MAIN, H5_MAIN)
    # debug: 前 100 只股票
    debug_insts = merged.index.get_level_values("instrument").unique()[:100]
    debug_df = merged.loc[pd.IndexSlice[:, debug_insts], :]
    save(debug_df, PARQUET_DEBUG, H5_DEBUG)
    print(f"\n=== Done! ===", flush=True)
    print(f"主数据: {len(merged):,} 行, {merged.index.get_level_values('instrument').nunique()} 只", flush=True)
    print(f"Debug : {len(debug_df):,} 行, {debug_df.index.get_level_values('instrument').nunique()} 只", flush=True)
    print(f"时间范围: {merged.index.get_level_values('date').min()} ~ {merged.index.get_level_values('date').max()}", flush=True)


if __name__ == "__main__":
    main()
