#!/usr/bin/env python3
"""
因子分析 + 选股 + 飞书推送 一体化脚本
=====================================
功能：
1. 运行 IC 因子分析 (run_ic_fast.py)
2. 基于 Top N 因子筛选股票
3. 推送结果到飞书

用法：
    python run_pipeline.py              # 完整流程
    python run_pipeline.py --ic-only    # 只跑 IC 分析
    python run_pipeline.py --stocks-only  # 只选股
    python run_pipeline.py --feishu-only --ic-results xxx.csv --stocks xxx.csv  # 仅推送
"""
import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

import config as cfg
from engine.factor import synthesize_daily_composite
from feishu_notify import send_combined_report

logger = logging.getLogger(__name__)


def run_ic_analysis(feishu_url: str = None):
    """运行 IC 因子分析"""
    logger.info("=" * 70)
    logger.info("  步骤 1/3: IC 因子分析")
    logger.info("=" * 70)
    cmd = [sys.executable, str(cfg.PROJECT_ROOT / "run_ic_fast.py")]
    if feishu_url:
        cmd.extend(["--feishu-url", feishu_url])
    result = subprocess.run(
        cmd,
        cwd=str(cfg.PROJECT_ROOT),
        capture_output=False,
    )
    return result.returncode == 0


def screen_stocks(ic_df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """
    基于 IC 结果筛选 Top N 因子对应的股票

    Args:
        ic_df: IC 分析结果 DataFrame
        top_n: 使用 Top N 个因子进行选股

    Returns:
        选股结果 DataFrame
    """
    logger.info("=" * 70)
    logger.info("  步骤 2/3: 基于 Top 因子选股")
    logger.info("=" * 70)

    # 获取 Top N 因子（按 |IC| 排序）
    ic_df_sorted = ic_df.copy()
    ic_df_sorted["_abs_ic"] = ic_df_sorted["IC_5d"].abs()
    top_factors = ic_df_sorted.nlargest(top_n, "_abs_ic")["factor_id"].tolist()

    logger.info("使用 Top %d 个因子进行选股", len(top_factors))
    for i, fid in enumerate(top_factors, 1):
        row = ic_df_sorted[ic_df_sorted["factor_id"] == fid].iloc[0]
        logger.info("  %d. %s  IC=%+.4f", i, fid[:30], row["IC_5d"])

    # 加载因子数据
    WS = cfg.RDAGENT_WORKSPACE

    logger.info("加载因子数据...")
    factor_dict = {}
    for fid in top_factors:
        h5 = WS / fid / "result.h5"
        if not h5.exists():
            logger.warning("未找到: %s", h5)
            continue
        try:
            df = pd.read_hdf(h5, key="data")
            col = df.columns[0]
            s = df[col].copy()
            if s.index.names[0] != "datetime":
                s.index = s.index.set_names(["datetime", "instrument"])
            s = s.reset_index()
            s.columns = ["datetime", "instrument", "factor_val"]
            factor_dict[fid] = s
            logger.info("  %s  %d rows", fid[:20], len(s))
        except Exception as e:
            logger.error("%s 加载失败: %s", fid[:20], e)

    if not factor_dict:
        logger.error("没有可用因子数据！")
        return None

    # 获取最新交易日
    all_dates = []
    for s in factor_dict.values():
        all_dates.extend(s["datetime"].unique())
    latest_date = max(all_dates)
    logger.info("最新交易日: %s", latest_date)

    # 使用 engine 统一合成逻辑
    logger.info("合成综合得分...")
    result_df = synthesize_daily_composite({fid: s.set_index("instrument")["factor_val"] for fid, s in factor_dict.items()})
    if result_df.empty:
        logger.error("综合得分为空")
        return None

    # 保存结果
    out_csv = cfg.PROJECT_ROOT / "top10_stocks_new.csv"
    result_df.to_csv(out_csv, index=False)
    logger.info("已保存: %s", out_csv)

    logger.info("=" * 70)
    logger.info("  TOP 10 股票 (最新日: %s)", latest_date)
    logger.info("=" * 70)
    for _, row in result_df.head(10).iterrows():
        logger.info("  #%d  %s  得分=%.4f", int(row["rank"]), row["instrument"], row["composite_score"])

    return result_df


def push_feishu(ic_df: pd.DataFrame, stocks_df: pd.DataFrame, feishu_url: str = None):
    """推送结果到飞书"""
    logger.info("=" * 70)
    logger.info("  步骤 3/3: 推送飞书通知")
    logger.info("=" * 70)

    if feishu_url:
        import feishu_notify
        feishu_notify.FEISHU_WEBHOOK_URL = feishu_url

    try:
        success = send_combined_report(ic_df, stocks_df, top_n=10)
        if success:
            logger.info("飞书推送成功")
        else:
            logger.warning("飞书推送失败")
    except Exception as e:
        logger.warning("飞书推送异常: %s", e)


def main():
    parser = argparse.ArgumentParser(description="因子分析 + 选股 + 飞书推送一体化")
    parser.add_argument("--ic-only", action="store_true", help="只运行 IC 分析")
    parser.add_argument("--stocks-only", action="store_true", help="只选股（不重新计算 IC）")
    parser.add_argument("--feishu-only", action="store_true", help="只推送飞书（使用已有结果文件）")
    parser.add_argument("--ic-results", help="指定 IC 结果 CSV 路径")
    parser.add_argument("--stocks", help="指定选股结果 CSV 路径")
    parser.add_argument("--top-n", type=int, default=10, help="Top N 因子数量 (默认 10)")
    parser.add_argument("--feishu-url", default=None, help="飞书 Webhook URL（覆盖环境变量）")
    args = parser.parse_args()

    t_start = time.time()

    if args.feishu_only:
        # 仅推送模式
        ic_path = Path(args.ic_results) if args.ic_results else cfg.PROJECT_ROOT / "ic_scan_results_new.csv"
        stocks_path = Path(args.stocks) if args.stocks else cfg.PROJECT_ROOT / "top10_stocks_new.csv"

        if not ic_path.exists():
            logger.error("IC 结果文件不存在: %s", ic_path)
            return 1
        if not stocks_path.exists():
            logger.error("选股结果文件不存在: %s", stocks_path)
            return 1

        ic_df = pd.read_csv(ic_path)
        stocks_df = pd.read_csv(stocks_path)
        push_feishu(ic_df, stocks_df, feishu_url=args.feishu_url)

    elif args.ic_only:
        # 只运行 IC 分析（内部已包含飞书推送）
        if not run_ic_analysis(feishu_url=args.feishu_url):
            logger.error("IC 分析失败")
            return 1

    elif args.stocks_only:
        # 只选股
        ic_path = cfg.PROJECT_ROOT / "ic_scan_results_new.csv"
        if not ic_path.exists():
            logger.error("IC 结果文件不存在，请先运行 IC 分析: %s", ic_path)
            return 1

        ic_df = pd.read_csv(ic_path)
        stocks_df = screen_stocks(ic_df, top_n=args.top_n)

        if stocks_df is not None:
            push_feishu(ic_df, stocks_df, feishu_url=args.feishu_url)

    else:
        # 完整流程
        if not run_ic_analysis(feishu_url=args.feishu_url):
            logger.error("IC 分析失败，终止流程")
            return 1

        ic_df = pd.read_csv(cfg.PROJECT_ROOT / "ic_scan_results_new.csv")
        stocks_df = screen_stocks(ic_df, top_n=args.top_n)

        if stocks_df is not None:
            push_feishu(ic_df, stocks_df, feishu_url=args.feishu_url)

    logger.info("完成！总耗时: %.1fs", time.time() - t_start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
