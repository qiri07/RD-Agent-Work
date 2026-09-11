#!/usr/bin/env python3
"""
全量因子选股 — 使用全部 66 个因子对全量股票进行筛选
============================================================
- 加载所有 66 个因子的 result.h5
- Z-score 标准化 + 等权合成
- 输出各日期的 Top-K 股票
- 输出 Top-K 股票的因子贡献分解
"""

import logging
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, str(Path(".").resolve()))
from feishu_notify import send_top_stocks

import config as cfg
from engine.factor import synthesize_daily_composite

logger = logging.getLogger(__name__)

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
            logger.info("  %s  %s  %d rows", fid[:12], fname[:25], len(df))
        except Exception as e:
            errors.append((fid, str(e)))
            logger.warning("  %s  %s", fid[:12], str(e)[:60])

    combined = pd.concat(factor_data, axis=1)
    # 再次确保去重
    combined = combined[~combined.index.duplicated(keep='first')]
    logger.info("共加载 %d 个因子，%d 个失败", len(factor_data), len(errors))
    return combined, errors


def get_latest_date(df):
    dates = df.index.get_level_values("datetime").drop_duplicates().sort_values()
    dates = dates[~pd.isna(dates)]
    return dates[-1] if len(dates) > 0 else None


# ─── 主逻辑 ─────────────────────────────────────────────────

def main():
    logger.info("=" * 70)
    logger.info("  全量因子选股 — 66 因子 × 5,553 股票")
    logger.info("=" * 70)

    # 1. 加载全量数据
    logger.info("加载所有因子数据...")
    combined, errors = load_all_factors()
    if combined.empty:
        logger.error("没有可用因子数据！")
        return

    logger.info("合并结果: %d 行 × %d 因子", combined.shape[0], combined.shape[1])
    latest = get_latest_date(combined)
    date_min = combined.index.get_level_values('datetime').min().date()
    logger.info("时间范围: %s ~ %s", date_min, latest.date())
    logger.info("股票数量: %d", combined.index.get_level_values('instrument').nunique())

    # 2. 构建因子数据 dict，使用 engine 统一合成接口
    factor_data = {col: combined[col] for col in combined.columns}
    logger.info("参与合成的因子数: %d", len(factor_data))

    # 3. 全历史选股 — 逐日调用 synthesize_daily_composite
    all_dates = combined.index.get_level_values("datetime").drop_duplicates().sort_values()
    all_dates = all_dates[~pd.isna(all_dates)]
    logger.info("全历史选股，共 %d 个交易日...", len(all_dates))

    rows_out = []
    for dt in all_dates:
        result = synthesize_daily_composite(factor_data, date=dt)
        if result.empty:
            continue
        for _, row in result.head(TOP_K).iterrows():
            rows_out.append({
                "date": dt.date(),
                "rank": int(row["rank"]),
                "stock": row["instrument"],
                "score": float(row["composite_score"]),
            })

    out_df = pd.DataFrame(rows_out)
    out_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    logger.info("已保存 %d 条记录 → %s", len(out_df), OUTPUT_FILE)

    # 4. 最新日 Top-K 展示
    latest = get_latest_date(combined)
    logger.info("=" * 70)
    logger.info("  最新交易日 %s  — Top %d 股票", latest.date(), TOP_K)
    logger.info("=" * 70)
    top_latest = out_df[out_df["date"] == latest.date()].head(TOP_K)
    logger.info("  %5s  %12s  %12s", "排名", "股票代码", "综合得分")
    logger.info("  %5s  %12s  %12s", "-----", "------------", "------------")
    for _, row in top_latest.iterrows():
        logger.info("  %5d  %12s  %12.4f", row['rank'], row['stock'], row['score'])

    # 5. Top K 股票的因子贡献（各因子对该股票得分的贡献）
    logger.info("\nTop %d 股票 — 各因子贡献明细（最新日）", TOP_K)
    top_stocks = top_latest["stock"].tolist()
    result_latest = synthesize_daily_composite(factor_data, date=latest)
    day_std = result_latest.set_index("instrument")

    for stock in top_stocks:
        if stock not in day_std.index:
            continue
        contribs = []
        for col in day_std.columns:
            if col in ("composite_score", "rank"):
                continue
            val = float(day_std.loc[stock, col])
            contribs.append((col, val))
        contribs.sort(key=lambda x: x[1], reverse=True)
        top3 = contribs[:3]
        bot3 = contribs[-3:]
        score = float(day_std.loc[stock, "composite_score"])
        logger.info("\n  [%s]  score=%.4f", stock, score)
        logger.info("    正向贡献最大:  %s", ", ".join(f"{c}={v:.4f}" for c, v in top3))
        logger.info("    负向贡献最大:  %s", ", ".join(f"{c}={v:.4f}" for c, v in bot3))

    # 6. 飞书推送最新日 Top K
    try:
        today_stocks = out_df[out_df["date"] == latest.date()].head(TOP_K).copy()
        today_stocks["rank"] = range(1, len(today_stocks) + 1)
        today_stocks["composite_score"] = today_stocks["score"]
        today_stocks = today_stocks[["rank", "stock", "composite_score"]]
        today_stocks.columns = ["rank", "instrument", "composite_score"]
        send_top_stocks(today_stocks, top_n=TOP_K)
    except Exception as e:
        logger.warning("飞书推送失败: %s", e)

    logger.info("\n选股完成！结果已保存至 %s", OUTPUT_FILE)
    logger.info("  共筛选 %d 个交易日，每日 Top %d 只", len(all_dates), TOP_K)
