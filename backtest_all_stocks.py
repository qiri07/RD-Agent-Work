#!/usr/bin/env python3
from __future__ import annotations
"""
全量股票回测 — 找出 Top N 收益最高的股票
===========================================
对全量 A 股（SH + SZ + BJ）执行买入持有回测，按总收益率排名，输出 Top N。
使用复权价格，考虑交易成本和涨跌停限制。

用法:
    python3 backtest_all_stocks.py          # 全量回测，输出 Top 10
    python3 backtest_all_stocks.py --top 20 # 输出 Top 20
    python3 backtest_all_stocks.py --days 365  # 仅最近 365 个交易日
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import argparse
import time
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

import config as cfg
from engine.pricing import PriceEngine
from trading_rules import get_board, is_limit_up, is_limit_down

ASTOCK_LOT_SIZE = 100
INITIAL_CAPITAL = cfg.BACKTEST_INITIAL_CAPITAL
COMMISSION_RATE = cfg.BACKTEST_COMMISSION_RATE
SLIPPAGE_RATE = cfg.BACKTEST_SLIPPAGE_RATE


def main():
    parser = argparse.ArgumentParser(description="全量股票买入持有回测")
    parser.add_argument("--top", type=int, default=10, help="输出 Top N")
    parser.add_argument("--days", type=int, default=None,
                        help="只取最近 N 个交易日（默认全量）")
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL,
                        help="初始资金")
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("  全量股票回测 — 买入持有策略 Top %d", args.top)
    logger.info("=" * 70)

    # 加载复权价格（优先使用矫正数据）
    logger.info("\n加载复权价格...")
    t0 = time.time()
    price_engine = PriceEngine()
    if cfg.DAILY_PV_FULL_CORRECTED_PQ.exists():
        logger.info(f"  使用矫正数据: {cfg.DAILY_PV_FULL_CORRECTED_PQ}")
        adj_prices, split_stocks = price_engine.compute_adjusted_prices(
            pd.read_parquet(cfg.DAILY_PV_FULL_CORRECTED_PQ)
        )
    else:
        logger.info(f"  使用原始数据: {cfg.DAILY_PV_FULL_PQ}")
        adj_prices, split_stocks = price_engine.compute_adjusted_prices()
    logger.info(f"  {len(adj_prices):,} 行, 拆分调整: {len(split_stocks)} 只  ({time.time()-t0:.1f}s)")

    # 排除测试数据
    adj_prices = adj_prices[~adj_prices.index.get_level_values('instrument').str.startswith('__')]

    # 统一索引名称
    if adj_prices.index.names != ['datetime', 'instrument']:
        adj_prices.index.names = ['datetime', 'instrument']

    # 日期范围
    all_dates = sorted(adj_prices.index.get_level_values('datetime').drop_duplicates())
    all_dates = [d for d in all_dates if not pd.isna(d)]
    if args.days and args.days < len(all_dates):
        dates = all_dates[-args.days:]
        logger.info(f"  交易日: {len(dates)} (最近 {args.days} 天, {dates[0].date()} ~ {dates[-1].date()})")
    else:
        dates = all_dates
        logger.info(f"  交易日: {len(dates)} ({dates[0].date()} ~ {dates[-1].date()})")

    # 构建价格查找 dict
    price_map = {}
    for (dt, inst), row in adj_prices.iterrows():
        price_map[(dt, inst)] = {
            'open': float(row['$open']),
            'close': float(row['$close']),
        }

    # 逐只股票计算买入持有收益
    logger.info("\n计算个股收益...")
    t0 = time.time()
    results = compute_stock_returns(price_map, dates, args.initial_capital)
    elapsed = time.time() - t0
    logger.info(f"  完成 {len(results)} 只股票 ({elapsed:.1f}s)")

    if results.empty:
        logger.warning("无有效个股数据")
        return

    # 按总收益率排序
    results = results.sort_values('total_return', ascending=False)
    top_n = min(args.top, len(results))

    # 输出 Top N
    logger.info(f"\n{'=' * 70}")
    logger.info(f"  Top {top_n} 收益最高股票（买入持有）")
    logger.info(f"{'=' * 70}")
    logger.info("  {:>3s}  {:>16s}  {:>8s}  {:>10s}  {:>10s}  {:>10s}".format(
        "#", "股票代码", "首收", "末收", "收益率", "天数"))
    logger.info("  " + "-" * 70)
    for rank, (inst, row) in enumerate(results.head(top_n).iterrows(), 1):
        logger.info(
            f"  {rank:>3d}  {inst:>16s}  {row['first_price']:>8.2f}  "
            f"{row['last_price']:>10.2f}  {row['total_return']:>+9.2f}%  "
            f"{int(row['trade_days']):>10d}"
        )

    # 保存结果
    output_csv = cfg.PROJECT_ROOT / "all_stocks_backtest.csv"
    results.to_csv(output_csv, encoding='utf-8-sig')
    logger.info(f"\n💾 完整结果已保存: {output_csv} ({len(results)} 只股票)")

    top_csv = cfg.PROJECT_ROOT / f"top{top_n}_stocks.csv"
    results.head(top_n).to_csv(top_csv, encoding='utf-8-sig')
    logger.info(f"💾 Top {top_n} 已保存: {top_csv}")

    # 飞书推送
    try:
        from feishu_notify import send_feishu
        lines = [
            f"📈 **全量股票回测 Top {top_n}**（买入持有）",
            f"🕐 {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"回测期间: {dates[0].date()} ~ {dates[-1].date()} ({len(dates)} 个交易日)",
            f"股票总数: {len(results)} 只",
            "",
            "**Top 10 收益最高股票:**",
        ]
        for rank, (inst, row) in enumerate(results.head(min(10, top_n)).iterrows(), 1):
            icon = "🟢" if row['total_return'] > 0 else "🔴"
            lines.append(
                f"  {icon} #{rank} {inst}  "
                f"收益={row['total_return']:+.2f}%  "
                f"首收={row['first_price']:.2f}  末收={row['last_price']:.2f}"
            )
        lines.append("")
        lines.append(f"💾 完整数据: all_stocks_backtest.csv")
        send_feishu("\n".join(lines))
    except Exception as e:
        logger.warning(f"飞书推送失败: {e}")


def compute_stock_returns(price_map: dict, dates: list, initial_capital: float) -> pd.DataFrame:
    """
    对每只股票计算买入持有收益。
    首日开盘价买入，末日收盘价卖出，考虑交易成本与涨跌停限制。

    Returns:
        DataFrame indexed by instrument, columns: first_date, last_date,
        first_price, last_price, total_return, trade_days, trade_count
    """
    all_instruments = sorted(set(
        inst for (dt, inst) in price_map.keys()
    ))

    results = []
    for inst in all_instruments:
        # 找首日有效价格
        buy_key = None
        buy_price = None
        for d in dates:
            key = (d, inst)
            if key in price_map:
                p = price_map[key]
                if p['open'] > 0 and p['close'] > 0:
                    buy_key = key
                    buy_price = p['open']
                    break

        if buy_key is None:
            continue

        # 找末日有效价格
        sell_key = None
        sell_price = None
        for d in reversed(dates):
            key = (d, inst)
            if key in price_map:
                p = price_map[key]
                if p['close'] > 0:
                    sell_key = key
                    sell_price = p['close']
                    break

        if sell_key is None or sell_price <= 0 or buy_price <= 0:
            continue

        if sell_key == buy_key:
            continue  # 只有一天数据，跳过

        # 检查买入是否涨停（首日开盘价 = 前日收盘的涨停价）
        buy_dt, _ = buy_key
        buy_idx = dates.index(buy_dt)
        can_buy = True
        if buy_idx > 0:
            prev_key = (dates[buy_idx - 1], inst)
            if prev_key in price_map:
                prev_close = price_map[prev_key]['close']
                if prev_close > 0:
                    board = get_board(inst)
                    if is_limit_up(buy_price, prev_close, board):
                        can_buy = False

        # 检查卖出是否跌停
        can_sell = True
        sell_dt, _ = sell_key
        sell_idx = dates.index(sell_dt)
        if sell_idx > 0:
            prev_key = (dates[sell_idx - 1], inst)
            if prev_key in price_map:
                prev_close = price_map[prev_key]['close']
                if prev_close > 0:
                    board = get_board(inst)
                    if is_limit_down(sell_price, prev_close, board):
                        can_sell = False

        if not can_buy or not can_sell:
            continue

        # 计算收益
        shares = int(initial_capital / buy_price / ASTOCK_LOT_SIZE) * ASTOCK_LOT_SIZE
        if shares <= 0:
            continue

        buy_cost = shares * buy_price * (1 + COMMISSION_RATE + SLIPPAGE_RATE)
        sell_value = shares * sell_price * (1 - COMMISSION_RATE - SLIPPAGE_RATE)
        total_return = (sell_value / buy_cost - 1) * 100

        trade_days = (sell_dt - buy_dt).days

        results.append({
            'instrument': inst,
            'first_date': buy_dt,
            'last_date': sell_dt,
            'first_price': round(buy_price, 2),
            'last_price': round(sell_price, 2),
            'total_return': round(total_return, 2),
            'trade_days': trade_days,
            'trade_count': 2,
        })

    df = pd.DataFrame(results)
    if df.empty:
        return df
    df = df.set_index('instrument')
    return df


if __name__ == "__main__":
    main()
