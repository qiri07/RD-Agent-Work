#!/usr/bin/env python3
"""
因子选股 TOP10 + 飞书推送
========================
1. 加载IC结果，按IC绝对值排序去重
2. 取Top N去重因子计算最新日综合得分
3. 选出TOP10股票
4. 推送飞书
"""
import logging
import sys
import time
from pathlib import Path

import pandas as pd

import config as cfg
from engine.factor import synthesize_daily_composite
from feishu_notify import send_feishu

logger = logging.getLogger(__name__)


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
    logger.info("IC去重: %d -> %d 个唯一因子", len(ic_df), len(ic_unique))
    return ic_unique


def load_factors(factor_ids):
    """从h5加载因子数据，返回 {fid: Series}"""
    WS = cfg.RDAGENT_WORKSPACE
    factor_data = {}
    for fid in factor_ids:
        h5 = WS / fid / "result.h5"
        if not h5.exists():
            logger.warning("跳过: %s (无h5)", fid[:20])
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
            logger.error("%s 加载失败: %s", fid[:20], e)
    return factor_data


def screen_top10(ic_df, top_n=10):
    """基于Top N去重因子筛选TOP10股票"""
    logger.info("=" * 60)
    logger.info("  因子选股 TOP10")
    logger.info("=" * 60)

    # 取Top N去重因子
    top_factors = ic_df.nlargest(top_n, "_abs_ic")["factor_id"].tolist()
    logger.info("使用 Top %d 个去重因子", len(top_factors))
    for i, fid in enumerate(top_factors, 1):
        row = ic_df[ic_df["factor_id"] == fid].iloc[0]
        icon = "OK" if row["IC_5d"] > 0 else "WARN"
        logger.info("  %s #%d  IC=%+.4f  %s", icon, i, row["IC_5d"], fid[:36])

    # 加载因子数据
    logger.info("加载因子数据...")
    factor_data = load_factors(top_factors)
    if not factor_data:
        raise RuntimeError("没有可用的因子数据")

    # 使用 engine 统一合成逻辑
    logger.info("合成综合得分...")
    result_df = synthesize_daily_composite(factor_data)
    if result_df.empty:
        raise RuntimeError("综合得分为空")

    logger.info("股票数: %d", len(result_df))

    top_k = 10
    top_stocks = result_df.head(top_k)

    # 保存结果
    out_csv = cfg.PROJECT_ROOT / "top10_stocks_new.csv"
    top_stocks.to_csv(out_csv, index=False)
    logger.info("已保存: %s", out_csv)

    logger.info("=" * 60)
    logger.info("  TOP %d 股票 (%s)", top_k, latest_date.strftime("%Y-%m-%d"))
    logger.info("=" * 60)
    for _, row in top_stocks.iterrows():
        logger.info("  #%d  %s  综合得分=%.3f", int(row["rank"]), row["instrument"], row["composite_score"])

    # 同时保存因子明细CSV
    detail_csv = cfg.PROJECT_ROOT / "top10_factor_detail.csv"
    result_df.to_csv(detail_csv, index=False)
    logger.info("因子明细: %s", detail_csv)

    return top_stocks, latest_date


def push_to_feishu(ic_df, stocks_df, latest_date):
    """推送结果到飞书"""
    logger.info("=" * 60)
    logger.info("  推送飞书通知")
    logger.info("=" * 60)

    top_factors = ic_df.nlargest(10, "_abs_ic")
    factor_lines = []
    for rank, (_, row) in enumerate(top_factors.head(5).iterrows(), 1):
        icon = "OK" if row["IC_5d"] > 0 else "WARN"
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
        logger.info("=" * 60)
        logger.info("  步骤 1/3: 加载IC结果")
        logger.info("=" * 60)
        ic_df = load_ic_results()

        # Step 2: 选股
        stocks_df, latest_date = screen_top10(ic_df, top_n=10)

        # Step 3: 飞书推送
        push_to_feishu(ic_df, stocks_df, latest_date)

        elapsed = time.time() - t_start
        logger.info("全部完成！耗时: %.1fs", elapsed)
        return 0

    except Exception as e:
        logger.exception("失败: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
