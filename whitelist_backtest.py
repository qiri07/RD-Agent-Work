#!/usr/bin/env python3
from __future__ import annotations

"""
白名单股票因子分析与回测
========================
对指定白名单股票进行因子计算、IC分析和回测
（独立运行脚本，导入 engine.factor_compute 共享模块）

用法:
    python3 whitelist_backtest.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from engine.backtest import BacktestEngine
from engine.factor_compute import load_whitelist_data, compute_factors, compute_ic, synthesize_score
from engine.metrics import PerformanceAnalyzer
from engine.pricing import PriceEngine

WHITELIST = cfg.WHITELIST_STOCKS

BACKTEST_TOP_K = 10
BACKTEST_HOLD_DAYS = 5
INITIAL_CAPITAL = 1_000_000


def run_backtest(df, factors_df, ic_df, top_k=10, hold_days=5):
    """运行回测"""
    print("\n🚀 运行回测...", flush=True)

    valid_factors = ic_df[ic_df['IC_5d'].abs() >= 0.005]['factor_id'].tolist()
    if len(valid_factors) >= 3:
        top_factors = ic_df.loc[ic_df['IC_5d'].abs().nlargest(5).index, 'factor_id'].tolist()
    else:
        top_factors = ic_df.head(3)['factor_id'].tolist()

    print(f"  使用因子: {top_factors}")

    all_dates = sorted(df.index.get_level_values('datetime').unique())
    signals = {}

    for i, date in enumerate(all_dates):
        try:
            day_factors = {}
            for fid in top_factors:
                if fid not in factors_df.columns:
                    continue
                day_data = factors_df.loc[date, fid]
                day_data = day_data.dropna()
                if len(day_data) >= top_k:
                    day_factors[fid] = day_data

            if not day_factors:
                continue

            result = synthesize_score(day_factors)
            if result is None or result.empty:
                continue

            top_stocks = result.head(top_k).index.tolist()
            signals[i] = top_stocks

        except Exception:  # noqa: BLE001,S110
            pass

    print(f"  生成信号: {len(signals)} 个交易日")

    price_engine = PriceEngine()
    price_map = price_engine.build_price_map(df)

    bt_engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
    result = bt_engine.run(all_dates, price_map, signals, hold_days, top_k)

    analyzer = PerformanceAnalyzer(initial_capital=INITIAL_CAPITAL)
    metrics = analyzer.analyze(result.daily_value, result.trades)

    print(f"\n{'='*60}")
    print("  回测结果")
    print(f"{'='*60}")
    print(f"  回测天数:           {metrics.total_days}")
    print(f"  初始资金:           {INITIAL_CAPITAL:,.0f} 元")
    print(f"  最终净值:           {metrics.final_value:,.0f} 元")
    print(f"  总收益率:           {metrics.total_return_pct:+.2f}%")
    print(f"  年化收益率:         {metrics.annual_return_pct:+.2f}%")
    print(f"  夏普比率:           {metrics.sharpe_ratio:.3f}")
    print(f"  最大回撤:           {metrics.max_drawdown_pct:.2f}%")
    print(f"  胜率:               {metrics.win_rate_pct:.1f}%")
    print(f"  总交易次数:         {metrics.total_trades}")
    print(f"  盈利交易:           {metrics.win_trades}")
    print(f"  盈亏比:             {metrics.profit_factor:.2f}")
    print(f"{'='*60}")

    return metrics, result


def main():
    t_start = time.time()

    if not cfg.is_whitelist_configured():
        print("❌ 白名单未配置，请在 .env 文件中设置 WHITELIST_STOCKS", flush=True)
        print("   示例: WHITELIST_STOCKS=SH600000,SH600001,SZ000001", flush=True)
        return 1

    print("=" * 70, flush=True)
    print("  白名单股票因子分析与回测", flush=True)
    print("=" * 70, flush=True)
    print(f"\n白名单: {len(WHITELIST)} 只股票", flush=True)
    print(f"        {', '.join(WHITELIST[:10])}" + ("..." if len(WHITELIST) > 10 else ""), flush=True)

    df = load_whitelist_data()
    factors_df = compute_factors(df)
    ic_df = compute_ic(factors_df, df)

    ic_df.to_csv('whitelist_ic_results.csv', index=False)
    print("\n💾 IC 结果已保存: whitelist_ic_results.csv")

    _, result = run_backtest(df, factors_df, ic_df,
                             top_k=BACKTEST_TOP_K,
                             hold_days=BACKTEST_HOLD_DAYS)

    nav_df = pd.DataFrame(result.daily_value)
    nav_df.to_csv('whitelist_backtest_nav.csv', index=False)

    trades_df = pd.DataFrame(result.trades)
    trades_df.to_csv('whitelist_backtest_trades.csv', index=False)

    print("\n💾 回测结果已保存:")
    print("  - whitelist_backtest_nav.csv")
    print("  - whitelist_backtest_trades.csv")

    print(f"\n总耗时: {time.time() - t_start:.1f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
