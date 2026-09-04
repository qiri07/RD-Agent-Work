#!/usr/bin/env python3
"""
RD-Agent 因子选股完整指南
========================================
演示如何使用生成的因子进行股票筛选和多因子组合
========================================
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

import config as cfg

WORKSPACE = cfg.RDAGENT_WORKSPACE


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def load_factor(factor_id):
    """加载单个因子，统一索引为 (datetime, instrument)"""
    result_file = WORKSPACE / factor_id / "result.h5"
    df = pd.read_hdf(result_file, key="data")
    fname = df.columns[0]
    df.columns = [fname]

    idx = df.index
    # 部分因子索引顺序是 (instrument, date)，需要交换
    if idx.names == ["instrument", "date"]:
        df.index = pd.MultiIndex.from_tuples(
            [(t[1], t[0]) for t in idx], names=["datetime", "instrument"]
        )
    elif idx.names[0] is None and idx.names[1] is None:
        # 通过首元素判断：SH6xxxxx 是股票代码，Timestamp 是日期
        first = idx[0]
        if isinstance(first[0], str) and first[0].startswith("SH"):
            df.index = pd.MultiIndex.from_tuples(
                [(t[1], t[0]) for t in idx], names=["datetime", "instrument"]
            )
        else:
            df.index.names = ["datetime", "instrument"]
    else:
        df.index.names = ["datetime", "instrument"]

    return df, fname


def standardize(df):
    """对各列做 Z-score 标准化"""
    result = df.copy()
    for col in result.columns:
        mean, std = result[col].mean(), result[col].std()
        result[col] = 0 if std == 0 else (result[col] - mean) / std
    return result


def get_latest_date(factor_df):
    """获取最新有效交易日"""
    dates = factor_df.index.get_level_values("datetime").drop_duplicates().sort_values()
    dates = dates[~pd.isna(dates)]
    return dates[-1] if len(dates) > 0 else None


# ═══════════════════════════════════════════════════════════
# 1. 单因子选股
# ═══════════════════════════════════════════════════════════

def screen_single_factor(factor_df, factor_name, top_k=10, date=None):
    """按单因子值选 Top-K 股票"""
    all_dates = factor_df.index.get_level_values("datetime").drop_duplicates().sort_values()
    all_dates = all_dates[~pd.isna(all_dates)]

    if date is None:
        date = all_dates[-1]
    else:
        mask = all_dates <= date
        date = all_dates[mask].max() if mask.any() else all_dates[0]

    day = factor_df.xs(date, level="datetime").copy()
    day = day.rename(columns={factor_name: "value"})
    day["rank"] = day["value"].rank(ascending=False, method="dense")
    return day.nlargest(top_k, "value"), date


# ═══════════════════════════════════════════════════════════
# 2. 多因子组合选股
# ═══════════════════════════════════════════════════════════

def screen_multi_factor(combined_df, top_k=10, weights=None, date=None):
    """多因子等权/加权合成选股"""
    if weights is None:
        weights = {col: 1.0 / len(combined_df.columns) for col in combined_df.columns}
    else:
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}

    # 标准化 + 加权合成
    norm = standardize(combined_df)
    norm["score"] = sum(norm[col] * w for col, w in weights.items() if col in norm.columns)

    # 获取所有交易日
    all_dates = norm.index.get_level_values("datetime").drop_duplicates().sort_values()
    all_dates = all_dates[~pd.isna(all_dates)]

    if date is None:
        date = all_dates[-1]
    else:
        # 找最近的不超过 target_date 的交易日
        mask = all_dates <= date
        if mask.any():
            date = all_dates[mask].max()
        else:
            date = all_dates[0]  # 取最早的交易日

    day = norm.xs(date, level="datetime").copy()
    day["rank"] = day["score"].rank(ascending=False, method="dense")
    return day.nlargest(top_k, "score"), date, weights


# ═══════════════════════════════════════════════════════════
# 主程序
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("  RD-Agent 因子选股完整指南")
    print("=" * 65)

    # ── 配置：选择要使用的因子（只选有 result.h5 的）──
    factor_pool = {
        "02d7dce95b7f410aa3ba2f8c2ab29b57": "10-day Momentum",
        "04d1651ebc7043c9bd047ca828cc479e": "volume_spike",
        "1e3c8739f45b4179bf192e0b7918bfb8": "intraday_range_pct",
        "f834f42beedd44bfa9238a8501b21b5c": "short_term_reversal_5d",
        "0fd8bca4102e45aebdb18af52d648d0e": "daily_return",
    }

    # ── 步骤1：加载因子 ──
    print("\n📂 步骤1：加载因子数据")
    print("-" * 65)
    factors = {}
    for fid, alias in factor_pool.items():
        df, fname = load_factor(fid)
        df = df.fillna(method="ffill").fillna(0)
        df.columns = [alias]
        factors[alias] = df[alias]
        print(f"  ✅ {alias:25s}  {len(df):>7,d} 条记录")

    combined = pd.concat(factors, axis=1)
    latest = get_latest_date(combined)
    print(f"\n  合并后: {combined.shape[0]:,} 行 × {combined.shape[1]} 个因子")
    print(f"  时间范围: {combined.index.get_level_values('datetime').min().date()} ~ {latest.date()}")
    print(f"  覆盖股票: {combined.index.get_level_values('instrument').nunique()} 只")

    # ── 步骤2：单因子选股 ──
    print("\n" + "=" * 65)
    print("📊 步骤2：单因子选股 — 各因子 Top 10（最新日）")
    print("=" * 65)

    for alias in factor_pool.values():
        top10, _ = screen_single_factor(combined[[alias]], alias, top_k=10)
        print(f"\n  【{alias}】")
        for i, (stock, row) in enumerate(top10.iterrows(), 1):
            print(f"    {i:2d}. {stock}  factor={row['value']:>8.4f}  rank={int(row['rank'])}")

    # ── 步骤3：多因子组合选股 ──
    print("\n" + "=" * 65)
    print("🎯 步骤3：多因子组合选股（等权合成 Top 10）")
    print("=" * 65)

    top10_multi, _, w = screen_multi_factor(combined, top_k=10)
    print(f"\n  合成日期: {latest.date()}")
    print(f"  等权权重: 每个因子 {1/len(combined.columns):.1%}")
    print(f"\n  {'排名':>4s}  {'股票代码':>10s}  {'综合得分':>10s}  {'排名':>6s}")
    print(f"  {'─'*4}  {'─'*10}  {'─'*10}  {'─'*6}")
    for i, (stock, row) in enumerate(top10_multi.iterrows(), 1):
        print(f"  {i:4d}  {stock:>10s}  {row['score']:>10.4f}  {int(row['rank']):>6d}")

    # ── 步骤4：指定日期选股演示 ──
    print("\n" + "=" * 65)
    print("📅 步骤4：指定日期选股（示例：2024-06-01）")
    print("=" * 65)

    target_date = pd.Timestamp("2024-06-01")
    all_dates = combined.index.get_level_values("datetime").drop_duplicates().sort_values()
    all_dates = all_dates[~pd.isna(all_dates)]
    actual_date = all_dates[all_dates <= target_date].max()
    print(f"  指定日期 {target_date.date()} 非交易日，使用最近交易日: {actual_date.date()}")
    top10_spec, spec_date, _ = screen_multi_factor(combined, top_k=10, date=actual_date)
    print(f"\n  选股日期: {spec_date.date()}")
    for i, (stock, row) in enumerate(top10_spec.iterrows(), 1):
        print(f"    {i:2d}. {stock}  score={row['score']:>8.4f}")

    # ── 步骤5：使用方法总结 ──
    print("\n" + "=" * 65)
    print("💡 如何使用因子选股：核心方法总结")
    print("=" * 65)
    print("""
┌──────────────────────────────────────────────────────────────────┐
│  方法一：单因子 Top-K 选股（最简单）                              │
│  ─────────────────────────────────                               │
│  df, name = load_factor("02d7dce95b7f410aa3ba2f8c2ab29b57")       │
│  top10, date = screen_single_factor(df, name, top_k=10)          │
│  → 输出当日因子值最高的10只股票                                   │
│                                                                  │
│  方法二：多因子等权合成选股（推荐）                                │
│  ─────────────────────────────────                               │
│  combined = pd.concat([df1, df2, df3], axis=1)                   │
│  top10, date, weights = screen_multi_factor(combined, top_k=10)  │
│  → 各因子先标准化，再等权加总，选得分最高的股票                    │
│                                                                  │
│  方法三：自定义权重多因子选股                                      │
│  ────────────────────────────────                                │
│  weights = {"10-day Momentum": 0.5, "volume_spike": 0.3,          │
│             "intraday_range_pct": 0.2}                           │
│  top10, date, _ = screen_multi_factor(combined, top_k=10,        │
│                                        weights=weights)          │
│  → 根据你的理解给不同因子分配不同权重                              │
│                                                                  │
│  方法四：指定历史日期选股                                         │
│  ────────────────────────────────                                │
│  top10, date = screen_single_factor(df, name,                   │
│                                      date=pd.Timestamp("2024-01-01"))
│  → 回溯历史任意一天的选股结果                                     │
└──────────────────────────────────────────────────────────────────┘

  实际应用注意事项：
  ① 回测时需要用 T-1 日的因子值决定 T 日买入（避免未来信息）
  ② 加入交易成本（佣金+滑点约 0.15%/次）会降低实际收益
  ③ 建议加入行业中性约束，避免单一行业过度集中
  ④ 可以进一步计算因子 IC（信息系数）来量化因子有效性
""")

    print("✅ 完成！")


if __name__ == "__main__":
    main()
