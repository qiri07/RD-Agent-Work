#!/usr/bin/env python3
"""
下载完整 A 股全量日线数据（来自 baostock）
支持断点续传，输出 parquet + hdf5 格式
"""
import sys, time, os
from pathlib import Path
import pandas as pd
import baostock as bs

BASE = Path(__file__).parent
PARQUET = BASE / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv.parquet"
H5 = BASE / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv.h5"
CKPT = BASE / ".dl_ckpt.pkl"
STOCK_LIST = BASE / ".astock_list.pkl"

START = "2018-01-01"
END = __import__('datetime').date.today().isoformat()
SLEEP = 0.18   # 每只股票间隔（秒）
TEMP_PARQUET = BASE / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv_temp.parquet"


def _save_temp_parquet(new_rows, existing):
    """定期保存临时 parquet，防止中断丢失数据"""
    if not new_rows:
        return
    new_df = pd.DataFrame(new_rows)
    if existing is not None:
        existing_reset = existing.reset_index()
        combined = pd.concat([existing_reset, new_df], ignore_index=True)
    else:
        combined = new_df
    combined["date"] = pd.to_datetime(combined["date"])
    combined = combined.dropna(subset=["$open", "$close", "$volume"])
    combined = combined[combined["$high"] > 0]
    combined = combined.reset_index(drop=True)
    combined = combined.sort_values(["instrument", "date"]).reset_index(drop=True)
    combined = combined.set_index(["date", "instrument"])
    for c in ["$open", "$close", "$high", "$low", "$volume", "$factor"]:
        if c not in combined.columns:
            combined[c] = 1.0 if c == "$factor" else 0.0
    combined = combined[["$open", "$close", "$high", "$low", "$volume", "$factor"]]
    combined.to_parquet(TEMP_PARQUET, engine="pyarrow")
    print(f"  [定期保存] 临时 parquet: {len(combined):,} 行", flush=True)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2800
    print(f"=== A 股日线数据下载 ===")
    print(f"目标: {n} 只 | {START} ~ {END}")

    # 加载股票列表
    if STOCK_LIST.exists():
        stocks = pd.read_pickle(STOCK_LIST).tolist()
        print(f"股票列表: {len(stocks)} 只")
    else:
        print("请先运行获取股票列表脚本")
        return

    # 加载检查点
    done = set()
    skipped = 0
    if CKPT.exists():
        cp = pd.read_pickle(CKPT)
        done = set(cp.get("done", []))
        skipped = cp.get("skipped", 0)
        print(f"恢复检查点: 已完成 {len(done)} 只，跳过 {skipped} 只")

    # 加载已有数据（合并 checkpoint 中的历史数据 + 临时文件）
    existing = None
    existing_done = set()
    # 先加载原始 parquet
    if PARQUET.exists():
        existing = pd.read_parquet(PARQUET)
        existing_done = set(existing.index.get_level_values("instrument").unique())
    # 再加载临时 parquet（可能包含新下载的数据）
    if TEMP_PARQUET.exists():
        temp_df = pd.read_parquet(TEMP_PARQUET)
        temp_done = set(temp_df.index.get_level_values("instrument").unique())
        if existing is not None:
            # 只取新增的股票数据
            new_only = temp_df[~temp_df.index.get_level_values("instrument").isin(existing_done)]
            if len(new_only) > 0:
                existing = pd.concat([existing.reset_index(), new_only.reset_index()], ignore_index=True)
                existing = existing.drop_duplicates(subset=["date", "instrument"], keep="last")
                existing = existing.set_index(["date", "instrument"])
        else:
            existing = temp_df
        existing_done |= temp_done
    if existing is not None:
        done |= existing_done
        print(f"已有数据: {len(existing):,} 行, {len(existing_done)} 只")

    to_dl = [s for s in stocks if s not in done][:n]
    print(f"待下载: {len(to_dl)} 只")

    if not to_dl:
        print("全部已完成！")
        return

    # 登录
    lg = bs.login()
    if lg.error_code != "0":
        print(f"登录失败: {lg.error_msg}")
        return
    print("baostock login OK")

    t0 = time.time()
    new_rows = []

    for i, code in enumerate(to_dl):
        if code.startswith('SH'):
            bs_code = 'sh.' + code[2:]
        elif code.startswith('SZ'):
            bs_code = 'sz.' + code[2:]
        else:
            print(f"  跳过无效代码: {code}")
            skipped += 1
            done.add(code)
            continue
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,code,open,high,low,close,volume",
            start_date=START, end_date=END,
            frequency="d", adjustflag="2",
        )
        count = 0
        try:
            while (rs.error_code == "0") & rs.next():
                r = rs.get_row_data()
                try:
                    new_rows.append({
                        "instrument": code,
                        "date": pd.to_datetime(r[0]),
                        "$open": float(r[2]) if r[2] else None,
                        "$close": float(r[3]) if r[3] else None,
                        "$high": float(r[4]) if r[4] else None,
                        "$low": float(r[5]) if r[5] else None,
                        "$volume": float(r[6]) if r[6] else None,
                        "$factor": 1.0,
                    })
                    count += 1
                except Exception:
                    pass
        except Exception as e:
            print(f"  {code} error: {e}")
            count = 0

        if count == 0:
            skipped += 1
        done.add(code)

        if (i + 1) % 100 == 0 or (i + 1) == len(to_dl):
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(to_dl) - i - 1) / rate if rate > 0 else 0
            print(f"  {i+1}/{len(to_dl)} ({(i+1)*100//len(to_dl)}%) | "
                  f"{elapsed:.0f}s elapsed, ~{eta:.0f}s ETA | "
                  f"新增 {len(new_rows):,} 行", flush=True)

            # 定期保存检查点和临时 parquet（防中断丢失）
            if (i + 1) % 200 == 0:
                pd.to_pickle({"done": list(done), "skipped": skipped}, CKPT)
                _save_temp_parquet(new_rows, existing)

        time.sleep(SLEEP)

    elapsed_total = time.time() - t0
    print(f"\n下载完成: {len(to_dl)} 只在 {elapsed_total:.0f}s 内完成")
    print(f"跳过 (无数据): {skipped} 只")

    # 保存检查点
    pd.to_pickle({"done": list(done), "skipped": skipped}, CKPT)

    # 合并并保存
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        # 统一格式：existing 可能是 MultiIndex，先 reset_index
        if existing is not None:
            existing_reset = existing.reset_index()
            combined = pd.concat([existing_reset, new_df], ignore_index=True)
        else:
            combined = new_df
    else:
        combined = existing
        if combined is not None:
            combined = combined.reset_index()
        print("没有新数据")

    combined["date"] = pd.to_datetime(combined["date"])
    combined = combined.dropna(subset=["$open", "$close", "$volume"])
    combined = combined[combined["$high"] > 0]
    # 统一整理为 DataFrame 再设索引
    combined = combined.reset_index(drop=True)
    combined = combined.sort_values(["instrument", "date"]).reset_index(drop=True)
    combined = combined.set_index(["date", "instrument"])
    for c in ["$open", "$close", "$high", "$low", "$volume", "$factor"]:
        if c not in combined.columns:
            combined[c] = 1.0 if c == "$factor" else 0.0
    combined = combined[["$open", "$close", "$high", "$low", "$volume", "$factor"]]

    n_stocks = combined.index.get_level_values("instrument").nunique()
    n_dates = combined.index.get_level_values("date").nunique()
    print(f"\n最终数据: {len(combined):,} 行, {n_stocks} 只股票, {n_dates} 个交易日")
    print(f"时间范围: {combined.index.get_level_values('date').min().date()} ~ "
          f"{combined.index.get_level_values('date').max().date()}")

    PARQUET.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(PARQUET, engine="pyarrow")
    print(f"parquet: {PARQUET} ({PARQUET.stat().st_size/1024/1024:.1f} MB)")

    try:
        combined.to_hdf(H5, key="data", mode="w")
        print(f"h5: {H5} ({H5.stat().st_size/1024/1024:.1f} MB)")
    except Exception as e:
        print(f"h5 保存跳过: {e}")

    bs.logout()
    print("\n=== Done! ===")


if __name__ == "__main__":
    main()
