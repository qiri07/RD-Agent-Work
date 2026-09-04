#!/usr/bin/env python3
"""
全量因子选股 — 使用全部 66 个因子对全量股票进行筛选
============================================================
- 加载所有 66 个因子的 result.h5
- Z-score 标准化 + 等权合成
- 输出各日期的 Top-K 股票
- 输出 Top-K 股票的因子贡献分解
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, str(Path(".").resolve()))
from feishu_notify import send_top_stocks

import config as cfg

WORKSPACE = cfg.RDAGENT_WORKSPACE
SOURCE_DATA = cfg.DAILY_PV_PQ
TOP_K = cfg.STOCK_TOP_K_DEFAULT
OUTPUT_FILE = cfg.FULL_STOCK_SELECTION_CSV


# ─── 工具函数 ───────────────────────────────────────────────

def load_all_factors():
    """加载所有 66 个因子的结果，返回 DataFrame (datetime, instrument) × 因子名"""
    factor_data = {}
    errors = []

    for session_dir in sorted(WORKSPACE.iterdir()):
        if not session_dir.is_dir():
            continue
        fid = session_dir.name
        h5_file = session_dir / "result.h5"
        if not h5_file.exists():
            continue

        try:
            df = pd.read_hdf(h5_file, key="data")
            fname = df.columns[0]
            df = df.rename(columns={fname: fid})

            # 统一索引为 (datetime, instrument)
            idx = df.index
            if idx.names == ["instrument", "date"]:
                df.index = pd.MultiIndex.from_tuples(
                    [(t[1], t[0]) for t in idx], names=["datetime", "instrument"]
                )
            elif idx.names == [None, None]:
                first = idx[0]
                if isinstance(first[0], str) and first[0].startswith(("SH", "SZ", "SH6", "SZ0", "SZ3")):
                    df.index = pd.MultiIndex.from_tuples(
                        [(t[1], t[0]) for t in idx], names=["datetime", "instrument"]
                    )
                else:
                    df.index.names = ["datetime", "instrument"]
            elif idx.names[0] != "datetime":
                df.index.names = ["datetime", "instrument"]

            df = df.ffill().fillna(0)
            # 去重：同一 (datetime, instrument) 只保留第一条
            df = df[~df.index.duplicated(keep='first')]
            factor_data[fid] = df[fid]
            print(f"  ✅ {fid[:12]}  {fname:25s}  {len(df):,} rows")
        except Exception as e:
            errors.append((fid, str(e)))
            print(f"  ❌ {fid[:12]}  {str(e)[:60]}")

    combined = pd.concat(factor_data, axis=1)
    # 再次确保去重
    combined = combined[~combined.index.duplicated(keep='first')]
    print(f"\n共加载 {len(factor_data)} 个因子，{len(errors)} 个失败")
    return combined, errors


def standardize_cross_section(df):
    """横截面 Z-score 标准化（按日期）"""
    return df.groupby(level="datetime", sort=False).transform(
        lambda x: (x - x.mean()) / x.std(ddof=0) if x.std(ddof=0) > 0 else 0
    )


def get_latest_date(df):
    dates = df.index.get_level_values("datetime").drop_duplicates().sort_values()
    dates = dates[~pd.isna(dates)]
    return dates[-1] if len(dates) > 0 else None


# ─── 主逻辑 ─────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  全量因子选股 — 66 因子 × 5,553 股票")
    print("=" * 70)

    # 1. 加载全量数据
    print("\n📂 加载所有因子数据...")
    combined, errors = load_all_factors()
    if combined.empty:
        print("没有可用因子数据！")
        return

    print(f"\n合并结果: {combined.shape[0]:,} 行 × {combined.shape[1]} 因子")
    latest = get_latest_date(combined)
    print(f"时间范围: {combined.index.get_level_values('datetime').min().date()} "
          f"~ {latest.date()}")
    print(f"股票数量: {combined.index.get_level_values('instrument').nunique():,}")

    # 2. 横截面标准化
    print("\n📐 横截面 Z-score 标准化...")
    standardized = standardize_cross_section(combined)
    nan_pct = standardized.isna().mean() * 100
    print(f"  各因子 NaN 比例: min={nan_pct.min():.1f}%  "
          f"max={nan_pct.max():.1f}%  mean={nan_pct.mean():.1f}%")

    # 3. 等权合成
    print("\n🎯 等权合成综合得分...")
    standardized = standardized.fillna(0)
    n_factors = standardized.shape[1]
    w = 1.0 / n_factors
    standardized["score"] = (standardized * w).sum(axis=1)

    # 4. 全历史选股 — 保存完整结果
    print("\n📋 全历史选股结果...")
    all_dates = standardized.index.get_level_values("datetime").drop_duplicates().sort_values()
    all_dates = all_dates[~pd.isna(all_dates)]

    rows_out = []
    for dt in all_dates:
        day = standardized.xs(dt, level="datetime")
        day_ranked = day.copy()
        day_ranked["rank"] = day_ranked["score"].rank(ascending=False, method="dense")
        top = day_ranked.nlargest(TOP_K, "score")
        for stock, row in top.iterrows():
            rows_out.append({
                "date": dt.date(),
                "rank": int(row["rank"]),
                "stock": stock,
                "score": row["score"],
            })

    out_df = pd.DataFrame(rows_out)
    out_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"  已保存 {len(out_df)} 条记录 → {OUTPUT_FILE}")

    # 5. 最新日 Top-K 展示
    print(f"\n{'='*70}")
    print(f"  最新交易日 {latest.date()}  — Top {TOP_K} 股票")
    print(f"{'='*70}")
    top_latest = out_df[out_df["date"] == latest.date()].head(TOP_K)
    print(f"  {'排名':>5s}  {'股票代码':>12s}  {'综合得分':>12s}")
    print(f"  {'─'*5}  {'─'*12}  {'─'*12}")
    for _, row in top_latest.iterrows():
        print(f"  {row['rank']:>5d}  {row['stock']:>12s}  {row['score']:>12.4f}")

    # 6. Top 30 股票的因子贡献（各因子对该股票得分的贡献）
    print(f"\n{'='*70}")
    print(f"  Top {TOP_K} 股票 — 各因子贡献明细（最新日）")
    print(f"{'='*70}")
    top_stocks = top_latest["stock"].tolist()
    day_raw = combined.xs(latest, level="datetime")
    day_std = standardized.xs(latest, level="datetime")

    for stock in top_stocks:
        if stock not in day_std.index:
            continue
        contributions = {}
        for col in day_std.columns:
            if col == "score":
                continue
            val = day_std.loc[stock, col]
            contributions[col] = val * w
        sorted_contrib = sorted(contributions.items(), key=lambda x: x[1], reverse=True)
        top3 = sorted_contrib[:3]
        bot3 = sorted_contrib[-3:]
        print(f"\n  【{stock}】  score={day_std.loc[stock, 'score']:.4f}")
        print(f"    正向贡献最大:  " + ", ".join(f"{c}={v:.4f}" for c, v in top3))
        print(f"    负向贡献最大:  " + ", ".join(f"{c}={v:.4f}" for c, v in bot3))

    # 7. 各因子有效性统计（IC）
    print(f"\n{'='*70}")
    print("  各因子有效性统计（最新日截面）")
    print(f"{'='*70}")
    print(f"  {'因子ID(前12位)':>16s}  {'均值':>8s}  {'标准差':>8s}  {'NaN%':>6s}")
    print(f"  {'─'*16}  {'─'*8}  {'─'*8}  {'─'*6}")
    for col in standardized.columns:
        if col == "score":
            continue
        s = standardized[col]
        print(f"  {col:>16s}  {s.mean():>8.4f}  {s.std():>8.4f}  {s.isna().mean()*100:>5.1f}%")

    print(f"\n✅ 选股完成！结果已保存至 {OUTPUT_FILE}")
    print(f"   共筛选 {len(all_dates)} 个交易日，每日 Top {TOP_K} 只")

    # 飞书推送最新日 Top K
    try:
        today_stocks = out_df[out_df["date"] == latest.date()].head(TOP_K).copy()
        today_stocks["rank"] = range(1, len(today_stocks) + 1)
        today_stocks["composite_score"] = today_stocks["score"]
        today_stocks = today_stocks[["rank", "stock", "composite_score"]]
        today_stocks.columns = ["rank", "instrument", "composite_score"]
        send_top_stocks(today_stocks, top_n=TOP_K)
    except Exception as e:
        print(f"⚠️ 飞书推送失败: {e}", flush=True)


if __name__ == "__main__":
    main()
