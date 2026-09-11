#!/usr/bin/env python3
"""
因子选股 TOP10 + 飞书推送
========================
1. 加载IC结果，按IC绝对值排序去重
2. 取Top N去重因子计算最新日综合得分
3. 选出TOP10股票
4. 推送飞书
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg
from feishu_notify import send_feishu


def load_ic_results():
    """加载IC分析结果，去重"""
    ic_path = cfg.PROJECT_ROOT / "ic_scan_results_new.csv"
    if not ic_path.exists():
        raise FileNotFoundError(f"IC结果文件不存在: {ic_path}")
    ic_df = pd.read_csv(ic_path).copy()
    ic_df["_abs_ic"] = ic_df["IC_5d"].abs()

    # 按IC绝对值降序，去重相同IC值（保留第一个=最强的那个）
    ic_sorted = ic_df.sort_values("_abs_ic", ascending=False)
    seen = set()
    unique_rows = []
    for _, row in ic_sorted.iterrows():
        key = round(row["IC_5d"], 6)
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)
    ic_unique = pd.DataFrame(unique_rows)
    print(f"  IC去重: {len(ic_df)} -> {len(ic_unique)} 个唯一因子")
    return ic_unique


def load_factors(factor_ids):
    """从h5加载因子数据，返回 {fid: Series}"""
    WS = cfg.RDAGENT_WORKSPACE
    factor_data = {}
    for fid in factor_ids:
        h5 = WS / fid / "result.h5"
        if not h5.exists():
            print(f"    ⚠️  跳过: {fid[:20]} (无h5)")
            continue
        try:
            df = pd.read_hdf(h5, key="data")
            col = df.columns[0]
            s = df[col].copy()
            # 确保索引名为 (datetime, instrument)
            if s.index.names != ["datetime", "instrument"]:
                s.index = s.index.set_names(["datetime", "instrument"])
            factor_data[fid] = s
        except Exception as e:
            print(f"    ❌ {fid[:20]} 加载失败: {e}")
    return factor_data


def screen_top10(ic_df, top_n=10):
    """基于Top N去重因子筛选TOP10股票"""
    print("\n" + "=" * 60)
    print("  🎯 因子选股 TOP10")
    print("=" * 60)

    # 取Top N去重因子
    top_factors = ic_df.nlargest(top_n, "_abs_ic")["factor_id"].tolist()
    print(f"\n  使用 Top {len(top_factors)} 个去重因子:")
    for i, fid in enumerate(top_factors, 1):
        row = ic_df[ic_df["factor_id"] == fid].iloc[0]
        icon = "🟢" if row["IC_5d"] > 0 else "🔴"
        print(f"    {icon} #{i:2d}  {fid[:36]:<36s} IC={row['IC_5d']:+.4f}")

    # 加载因子数据
    print("\n  加载因子数据...")
    factor_data = load_factors(top_factors)
    if not factor_data:
        raise RuntimeError("没有可用的因子数据")

    # 获取最新交易日
    latest_dates = []
    for s in factor_data.values():
        d = s.index.get_level_values("datetime").max()
        latest_dates.append(d)
    latest_date = max(latest_dates)
    print(f"  最新交易日: {latest_date.strftime('%Y-%m-%d')}")

    # 提取最新日期的因子值
    day_scores = {}
    for fid, s in factor_data.items():
        mask = s.index.get_level_values("datetime") == latest_date
        day_vals = s[mask]
        if len(day_vals) > 0:
            day_scores[fid] = day_vals
    print(f"  共 {len(day_scores)} 个因子有最新日期数据")

    # 构建 DataFrame
    score_rows = []
    instruments = set()
    for fid, s in day_scores.items():
        for idx, val in s.items():
            inst = idx[1] if isinstance(idx, tuple) else idx
            instruments.add(inst)
            score_rows.append({"instrument": inst, "factor_id": fid, "score": val})

    df_scores = pd.DataFrame(score_rows)
    pivot = df_scores.pivot(index="instrument", columns="factor_id", values="score")
    print(f"  股票数: {len(pivot):,}")

    # Z-score 标准化
    pivot_std = pivot.copy()
    for col in pivot_std.columns:
        mean = pivot_std[col].mean()
        std = pivot_std[col].std()
        if std > 0:
            pivot_std[col] = (pivot_std[col] - mean) / std
        else:
            pivot_std[col] = 0.0

    # 等权合成综合得分
    n_factors = len(pivot_std.columns)
    pivot_std["composite_score"] = pivot_std.mean(axis=1)

    # 排序取Top K（保留所有列）
    top_k = 10
    pivot_std["rank"] = pivot_std["composite_score"].rank(ascending=False, method="dense")
    top_stocks = pivot_std.nlargest(top_k, "composite_score").reset_index()
    top_stocks = top_stocks.rename(columns={"index": "instrument"})

    # 拼接各因子Z-score列（保留factor columns顺序）
    factor_cols = [c for c in pivot_std.columns if c not in ("composite_score", "rank")]
    out_df = top_stocks[["rank", "instrument", "composite_score"] + factor_cols]

    # 保存结果
    out_csv = cfg.PROJECT_ROOT / "top10_stocks_new.csv"
    out_df.to_csv(out_csv, index=False)
    print(f"\n  💾 已保存: {out_csv}")

    print(f"\n{'='*60}")
    print(f"  🏆 Top {top_k} 股票 ({latest_date.strftime('%Y-%m-%d')})")
    print(f"{'='*60}")
    for _, row in out_df.iterrows():
        print(f"  #{int(row['rank']):2d}  {row['instrument']:12s}  综合得分={row['composite_score']:.3f}")

    # 同时保存因子明细CSV
    detail_csv = cfg.PROJECT_ROOT / "top10_factor_detail.csv"
    out_df.to_csv(detail_csv, index=False)
    print(f"  💾 因子明细: {detail_csv}")

    return out_df, latest_date


def push_to_feishu(ic_df, stocks_df, latest_date):
    """推送结果到飞书"""
    print("\n" + "=" * 60)
    print("  📱 推送飞书通知")
    print("=" * 60)

    top_factors = ic_df.nlargest(10, "_abs_ic")
    factor_lines = []
    for rank, (_, row) in enumerate(top_factors.head(5).iterrows(), 1):
        icon = "🟢" if row["IC_5d"] > 0 else "🔴"
        factor_lines.append(
            f"  {icon} #{rank}  IC={row['IC_5d']:+.4f}  t={row['IC_t_5d']:.1f}  {row['factor_id'][:20]}"
        )

    stock_lines = []
    for _, row in stocks_df.head(10).iterrows():
        stock_lines.append(f"  #{int(row['rank']):2d}  {row['instrument']}  得分={row['composite_score']:.3f}")

    text = (
        f"📈 RD-Agent 因子选股日报\n"
        f"📅 {latest_date.strftime('%Y-%m-%d')} | 5552只A股\n\n"
        f"━━━ Top 5 因子 ━━━\n"
        + "\n".join(factor_lines)
        + f"\n\n━━━ TOP 10 股票 ━━━\n"
        + "\n".join(stock_lines)
        + f"\n\n💾 详情: top10_stocks_new.csv"
    )

    success = send_feishu(text)
    return success


def main():
    t_start = time.time()

    try:
        # Step 1: 加载并去重IC结果
        print("\n" + "=" * 60)
        print("  📊 步骤 1/3: 加载IC结果")
        print("=" * 60)
        ic_df = load_ic_results()

        # Step 2: 选股
        stocks_df, latest_date = screen_top10(ic_df, top_n=10)

        # Step 3: 飞书推送
        push_to_feishu(ic_df, stocks_df, latest_date)

        elapsed = time.time() - t_start
        print(f"\n✅ 全部完成！耗时: {elapsed:.1f}s")
        return 0

    except Exception as e:
        print(f"\n❌ 失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
