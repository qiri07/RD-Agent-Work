#!/usr/bin/env python3
"""
单只股票全量分析工具
====================
用法:
    from stock_analyzer import analyze_stock
    analyze_stock('SH601668')          # 股票代码
    analyze_stock('中国建筑')           # 中文名称
    analyze_stock('SZ002027', out_dir='outputs/my_stock')

注意: 本模块是向后兼容的薄包装，核心逻辑已迁移到 stock_analyzer/ 子包。
"""
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

import config as cfg
from stock_analyzer.constants import SRC_PQ, INITIAL_CAPITAL
from stock_analyzer.resolver import resolve_ticker
from stock_analyzer.analyzer import (
    compute_factors, compute_returns, compute_stats,
    compute_yearly_stats, compute_ic_records,
)
from stock_analyzer.backtest import run_all_backtests
from stock_analyzer.report import (
    generate_report, save_cross_sectional_ic, save_ranking,
)


def analyze_stock(name_or_code: str, out_dir: str = None):
    """
    单只股票全量分析

    Args:
        name_or_code: 股票代码（如 SH601668）或中文名称（如 中国建筑）
        out_dir: 输出目录，默认 outputs/{ticker}_analysis

    Returns:
        dict: 包含所有分析结果的字典
    """
    ticker, display_name = resolve_ticker(name_or_code)
    if out_dir is None:
        out_dir = Path('outputs') / f'{ticker.lower()}_analysis'
    else:
        out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(f"  {display_name} ({ticker}) 全量历史分析")
    print("=" * 70)

    # ═══════════════════════════════════════════
    # 1. 数据加载
    # ═══════════════════════════════════════════
    print("\n【1. 数据加载】")
    df = pd.read_parquet(SRC_PQ)
    stock = df.xs(ticker, level='instrument', drop_level=False).sort_index()
    dates = stock.index.get_level_values(0)
    n_days = len(stock)
    print(f"  区间: {dates.min().date()} ~ {dates.max().date()}, {n_days:,} 交易日")
    stock.to_parquet(out_dir / f'{ticker.lower()}_raw.parquet')

    # ═══════════════════════════════════════════
    # 2. 收益分析
    # ═══════════════════════════════════════════
    print("\n【2. 收益分析】")
    close = stock['$close']
    volume = stock['$volume']

    stock_reset = compute_returns(stock.reset_index())
    daily_ret = stock_reset['ret_1d'].dropna()
    stats = compute_stats(daily_ret)

    stock_full = stock_reset.reset_index()
    yearly_stats = compute_yearly_stats(stock_full)

    print(f"  年化收益: {stats['ann_ret']*100:+.1f}%, "
          f"波动: {stats['ann_vol']*100:.1f}%, "
          f"夏普: {stats['sharpe']:.2f}, "
          f"最大回撤: {stats['max_dd']*100:.1f}%")
    stock_reset.to_parquet(out_dir / f'{ticker.lower()}_returns.parquet')

    # ═══════════════════════════════════════════
    # 3. 因子计算
    # ═══════════════════════════════════════════
    print("\n【3. 因子计算】")
    factor_df = compute_factors(stock, df)
    print(f"  计算 {len(factor_df.columns)} 个因子")
    factor_df.to_parquet(out_dir / f'{ticker.lower()}_factors.parquet')

    # ═══════════════════════════════════════════
    # 4. 横截面 IC 定位
    # ═══════════════════════════════════════════
    print("\n【4. 横截面 IC 定位】")
    workspace = cfg.RDAGENT_WORKSPACE
    n_matched = save_cross_sectional_ic(ticker, workspace, out_dir)
    print(f"  匹配 {n_matched} 个 RD-Agent 因子")
    save_ranking(ticker, dates, workspace, out_dir)

    # ═══════════════════════════════════════════
    # 5. 单股票 IC 检验
    # ═══════════════════════════════════════════
    print("\n【5. 因子有效性检验（单股票 IC）】")
    forward_ret = stock_reset['ret_5d'].dropna()
    ic_records = compute_ic_records(factor_df, forward_ret)
    for rec in ic_records:
        sig_mark = '✅' if rec['significant'] else '❌'
        print(f"    {rec['factor']:<20s}: IC={rec['IC']:+.4f}, "
              f"p={rec['p_value']:.2e} {sig_mark}")
    if ic_records:
        ic_df2 = pd.DataFrame(ic_records)
        ic_df2.to_csv(out_dir / f'{ticker.lower()}_factor_ic.csv', index=False)

    # ═══════════════════════════════════════════
    # 6. 回测验证
    # ═══════════════════════════════════════════
    print("\n【6. 回测验证】")
    backtest_results = run_all_backtests(stock, factor_df)

    print(f"\n  {'策略':<20s} {'最终价值':>12s} {'收益率':>10s} {'夏普':>8s} {'最大回撤':>10s} {'交易':>6s}")
    print("  " + "-" * 70)
    for r in backtest_results:
        print(f"  {r['strategy']:<20s} {r['final_value']:>12,.0f} "
              f"{r['return_pct']:>+9.1f}% {r['sharpe']:>+7.2f} "
              f"{r['max_drawdown_pct']:>+9.1f}% {r['n_trades']:>6d}")

    if backtest_results:
        pd.DataFrame(backtest_results).to_csv(
            out_dir / f'{ticker.lower()}_backtest.csv', index=False
        )

    # ═══════════════════════════════════════════
    # 7. 综合报告
    # ═══════════════════════════════════════════
    report = generate_report(
        ticker=ticker,
        display_name=display_name,
        src_pq=SRC_PQ,
        dates=dates,
        n_days=n_days,
        close=close,
        stats=stats,
        yearly_stats=yearly_stats,
        backtest_results=backtest_results,
        ic_records=ic_records,
        factor_df=factor_df,
        out_dir=out_dir,
    )

    print(f"\n  💾 报告已保存: {out_dir / f'{ticker.lower()}_report.json'}")
    print(f"\n  文件列表:")
    for f in sorted(out_dir.iterdir()):
        print(f"    - {f.name} ({f.stat().st_size / 1024:.1f} KB)")

    return report


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python stock_analyzer.py <股票代码或中文名> [输出目录]")
        print("示例: python stock_analyzer.py SH601668")
        print("      python stock_analyzer.py 中国建筑")
        print("      python stock_analyzer.py SZ002027 outputs/my_stock")
        sys.exit(1)

    ticker_input = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    analyze_stock(ticker_input, out_dir=out)
