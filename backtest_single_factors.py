#!/usr/bin/env python3
"""
单因子回测扫描 v4 — 每个因子独立按日选 Top-K，找出胜率 Top 3
============================================================
架构：使用 engine/ 模块
"""
import pandas as pd
import numpy as np
from pathlib import Path
import warnings, time
warnings.filterwarnings('ignore')

import config as cfg
from engine.pricing import PriceEngine
from engine.backtest import BacktestEngine, create_backtest_engine
from engine.factor import FactorEngine, create_factor_engine
from engine.metrics import PerformanceAnalyzer, create_performance_analyzer

WORKSPACE = cfg.RDAGENT_WORKSPACE
SOURCE_PQ = cfg.DAILY_PV_FULL_PQ

INITIAL_CAPITAL = cfg.BACKTEST_INITIAL_CAPITAL
COMMISSION = cfg.BACKTEST_COMMISSION_RATE
SLIPPAGE = cfg.BACKTEST_SLIPPAGE_RATE
MIN_TRADE = cfg.BACKTEST_MIN_TRADE_VALUE
SPLIT_CURR = pd.Timestamp(cfg.BACKTEST_SPLIT_DATE_CURR or "2026-09-02")
SPLIT_PREV = pd.Timestamp(cfg.BACKTEST_SPLIT_DATE_PREV or "2026-09-01")
TOP_K = cfg.BACKTEST_TOP_K
HOLD = cfg.BACKTEST_HOLD_DAYS


def main():
    print("=" * 70)
    print("  单因子回测扫描 v4 — 胜率 Top 3")
    print("=" * 70)

    # 初始化引擎
    price_engine = PriceEngine()
    backtest_engine = create_backtest_engine(
        initial_capital=INITIAL_CAPITAL,
        commission_rate=COMMISSION,
        slippage_rate=SLIPPAGE,
        min_trade_value=MIN_TRADE,
        lot_size=100
    )
    factor_engine = create_factor_engine(WORKSPACE)
    perf_analyzer = create_performance_analyzer(INITIAL_CAPITAL)

    print("\n📂 加载因子得分...")
    t0 = time.time()
    scores = factor_engine.load_all_factors()
    print(f"  {scores.shape[0]:,} 行 × {scores.shape[1]} 因子  ({time.time()-t0:.1f}s)")

    print("\n📂 加载价格数据...")
    prices = price_engine.load_prices()
    prices = prices[~prices.index.duplicated(keep='first')]
    # 复权处理
    prices, _ = price_engine.compute_adjusted_prices(prices)
    print(f"  {len(prices):,} 行, {prices.index.get_level_values('instrument').nunique():,} 只")

    print(f"\n🚀 开始回测 ({scores.shape[1]} 个因子)...")
    results = backtest_all_factors(scores, prices, backtest_engine)

    if not results:
        print("无有效结果！")
        return

    # 按胜率排序
    results.sort(key=lambda x: x['win_rate'], reverse=True)

    print(f"\n{'='*70}")
    print(f"  全因子排名 (Top 15)")
    print(f"{'='*70}")
    print(f"  {'#':>3s}  {'因子ID':>16s}  {'胜率':>6s}  {'总收益':>8s}  {'交易数':>6s}  {'盈亏比':>6s}")
    print(f"  {'─'*3}  {'─'*16}  {'─'*6}  {'─'*8}  {'─'*6}  {'─'*6}")
    for rank, r in enumerate(results[:15], 1):
        print(f"  {rank:>3d}  {r['factor_id']:>16s}  {r['win_rate']:>5.1f}%  "
              f"{r['total_return']:>+7.2f}%  {r['total_trades']:>6d}  {r['profit_factor']:>6.2f}")

    # Top 3 详细
    print(f"\n{'='*70}")
    print(f"  🏆 Top 3 高胜率因子")
    print(f"{'='*70}")

    top3 = results[:3]
    for rank, r in enumerate(top3, 1):
        trades = r['trades']
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t <= 0]
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 0

        rets = pd.Series(trades)
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0

        print(f"\n  #{rank}  因子ID: {r['factor_id']}")
        print(f"  {'─'*50}")
        print(f"  胜率:           {r['win_rate']:.1f}%  ({r['win_trades']}/{r['total_trades']}笔)")
        print(f"  总收益率:       {r['total_return']:+.2f}%")
        print(f"  最终净值:       {r['final_value']:,.0f} 元")
        print(f"  夏普比率:       {sharpe:.3f}")
        print(f"  平均盈利:       {avg_win:+.2f}%")
        print(f"  平均亏损:       {avg_loss:+.2f}%")
        print(f"  盈亏比:         {r['profit_factor']:.2f}")

        tdf = pd.DataFrame({'pnl_pct': trades})
        tdf.to_csv(f"top3_factor_{rank}_{r['factor_id']}.csv", index=False)
        print(f"  💾 已保存: top3_factor_{rank}_{r['factor_id']}.csv")

    print(f"\n{'='*70}")
    print(f"  Top 3 因子 — 交易统计")
    print(f"{'='*70}")
    for rank, r in enumerate(top3, 1):
        trades = r['trades']
        print(f"\n  #{rank} {r['factor_id'][:24]}")
        print(f"    交易分布: 盈利{sum(1 for t in trades if t>0)}笔  亏损{sum(1 for t in trades if t<=0)}笔")
        print(f"    最大单笔盈利: {max(trades):+.2f}%")
        print(f"    最大单笔亏损: {min(trades):+.2f}%")


def backtest_all_factors(scores_df, prices_df, engine: BacktestEngine):
    """对每个因子独立回测，返回结果列表"""
    prices = prices_df.sort_index()
    dates = sorted(prices.index.get_level_values('datetime').drop_duplicates())
    dates = [d for d in dates if not pd.isna(d) and d < SPLIT_CURR]
    if len(dates) < 2:
        return []

    # 构建价格查找 dict
    price_map = {}
    for (dt, inst), row in prices.iterrows():
        price_map[(dt, inst)] = {'open': row['$open'], 'close': row['$close']}

    factor_ids = list(scores_df.columns)
    results = []
    t0 = time.time()

    for fid in factor_ids:
        factor_series = scores_df[fid]
        day_topk = compute_day_topk(factor_series)
        n_valid = len(day_topk)
        if n_valid < 10:
            continue

        # 构建信号
        signals = {i: day_topk.get(dates[i], []) for i in range(len(dates)) if dates[i] in day_topk}

        result = engine.run(dates, price_map, signals, hold_days=HOLD, top_k=TOP_K)
        trades = result.trades
        
        # 提取盈亏百分比
        pnl_list = [t.get('pnl_pct', 0) for t in trades if t.get('action') == 'SELL']
        
        if not pnl_list:
            continue

        final_value = result.daily_value[-1]['value'] if result.daily_value else INITIAL_CAPITAL
        total_ret = (final_value / INITIAL_CAPITAL - 1) * 100
        wins = [t for t in pnl_list if t > 0]
        losses = [t for t in pnl_list if t <= 0]
        win_rate = len(wins) / len(pnl_list) * 100 if pnl_list else 0
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 1
        pf = avg_win / avg_loss if avg_loss > 0 else float('inf')

        elapsed = time.time() - t0
        print(f"  [{fid[:12]}] 胜率={win_rate:.1f}% 收益={total_ret:+.1f}%  "
              f"交易={len(pnl_list)} 选股日={n_valid}  ({elapsed:.0f}s)", flush=True)

        results.append({
            'factor_id': fid,
            'total_return': round(total_ret, 2),
            'win_rate': round(win_rate, 1),
            'total_trades': len(pnl_list),
            'win_trades': len(wins),
            'profit_factor': round(pf, 2),
            'final_value': round(final_value, 0),
            'trades': pnl_list,
        })

    return results


def compute_day_topk(scores_series):
    """对单个因子序列，按日计算 Top-K 股票列表"""
    day_topk = {}
    for dt, group in scores_series.groupby(level='datetime', sort=False):
        group = group.dropna()
        group = group[np.isfinite(group)]
        if len(group) < TOP_K:
            continue
        top = group.nlargest(TOP_K)
        day_topk[dt] = top.index.tolist()
    return day_topk


if __name__ == "__main__":
    main()
