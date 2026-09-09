#!/usr/bin/env python3
"""
因子选股策略回测 v2 — 全量复权价格
===================================
- 检测 2026-09-02 大规模股票拆分（126只）
- 对全量历史价格应用复权调整
- 使用复权价格重新计算因子得分和回测

架构：使用 engine/ 模块
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

import config as cfg
from engine.pricing import PriceEngine
from engine.backtest import BacktestEngine, create_backtest_engine
from engine.factor import FactorEngine, create_factor_engine
from engine.metrics import PerformanceAnalyzer, create_performance_analyzer
from logging_config import setup_logging

# ─── 参数（统一从 config 读取，支持环境变量覆盖）──────────────
TOP_K = cfg.BACKTEST_TOP_K
HOLD_DAYS = cfg.BACKTEST_HOLD_DAYS
INITIAL_CAPITAL = cfg.BACKTEST_INITIAL_CAPITAL
COMMISSION_RATE = cfg.BACKTEST_COMMISSION_RATE
SLIPPAGE_RATE = cfg.BACKTEST_SLIPPAGE_RATE
MIN_TRADE_VALUE = cfg.BACKTEST_MIN_TRADE_VALUE
SPLIT_RATIO_THRESHOLD = cfg.BACKTEST_SPLIT_RATIO_THRESHOLD

# A股交易单位：每手 100 股
ASTOCK_LOT_SIZE = 100

# 拆分日期
_split_prev, _split_curr = cfg.get_split_dates()
SPLIT_DATE_PREV = pd.Timestamp(_split_prev) if _split_prev else pd.Timestamp("2026-09-01")
SPLIT_DATE_CURR = pd.Timestamp(_split_curr) if _split_curr else pd.Timestamp("2026-09-02")


def main():
    logger.info("=" * 70)
    logger.info("  因子选股策略回测 v2 — 66 因子 Top 10（全量复权价格）")
    logger.info("=" * 70)

    # 初始化引擎
    price_engine = PriceEngine()
    backtest_engine = create_backtest_engine(
        initial_capital=INITIAL_CAPITAL,
        commission_rate=COMMISSION_RATE,
        slippage_rate=SLIPPAGE_RATE,
        min_trade_value=MIN_TRADE_VALUE,
        lot_size=ASTOCK_LOT_SIZE
    )
    factor_engine = create_factor_engine()
    perf_analyzer = create_performance_analyzer(INITIAL_CAPITAL)

    # 步骤1: 计算复权价格
    logger.info("\n📂 步骤1: 计算复权价格...")
    adj_prices, split_stocks = price_engine.compute_adjusted_prices()
    logger.info(f"  检测到 {len(split_stocks)} 只股票发生拆分")

    # 步骤2: 加载因子得分
    logger.info("\n📂 步骤2: 加载因子得分...")
    scores = factor_engine.load_all_factors()

    # 步骤3: 运行回测
    logger.info(f"\n🚀 步骤3: 回测 (Top {TOP_K}, 持仓 {HOLD_DAYS} 天)...")
    daily_value, trade_log = run_backtest(
        adj_prices, scores, backtest_engine, TOP_K, HOLD_DAYS
    )

    # 步骤4: 计算指标
    print("\n📊 回测结果")
    print("-" * 70)
    metrics = perf_analyzer.analyze(daily_value, trade_log)
    print(perf_analyzer.generate_report(metrics))

    # 保存结果
    df = pd.DataFrame(daily_value).dropna(subset=['value']).set_index('date').sort_index()
    metrics.final_nav = df['value'].iloc[-1] / INITIAL_CAPITAL
    metrics.nav_curve = df[['value']].copy()
    metrics.nav_curve.to_csv("backtest_nav.csv")
    pd.DataFrame(trade_log).to_csv("backtest_trades.csv", index=False, encoding='utf-8-sig')
    print(f"\n💾 已保存: backtest_nav.csv, backtest_trades.csv")

    # 月度统计
    print("\n📅 月度收益统计:")
    print("-" * 70)
    monthly = perf_analyzer.monthly_stats(daily_value)
    print(f"  {'月份':>10s}  {'起始净值':>12s}  {'期末净值':>12s}  {'月收益':>8s}")
    print(f"  {'─'*10}  {'─'*12}  {'─'*12}  {'─'*8}")
    for idx, row in monthly.iterrows():
        sign = "+" if row['ret'] >= 0 else ""
        print(f"  {str(idx):>10s}  {row['start_val']:>12,.0f}  {row['end_val']:>12,.0f}  {sign}{row['ret']:>6.2f}%")

    # ASCII 净值曲线
    print("\n📈 净值曲线（ASCII）")
    print("-" * 70)
    nav = df['value'] / INITIAL_CAPITAL
    sample_idx = np.linspace(0, len(nav) - 1, 100, dtype=int)
    sample_nav = nav.iloc[sample_idx]
    nav_min, nav_max = sample_nav.min(), sample_nav.max()
    width, height = 60, 15
    if nav_max == nav_min:
        nav_max = nav_min + 0.01
    for row in range(height, -1, -1):
        threshold = nav_min + (nav_max - nav_min) * row / height
        line = ""
        for val in sample_nav:
            line += "█" if val >= threshold - (nav_max - nav_min) / (2 * height) else " "
        print(f"  {threshold:5.2f} │{line}│")
    print(f"        └{'─' * width}┘")
    print(f"         {nav.index[sample_idx[0]].date()}        {nav.index[sample_idx[-1]].date()}")

    # 分阶段统计
    print("\n📊 分阶段统计:")
    print("-" * 70)
    periods = cfg.BACKTEST_PERIODS
    for name, start, end in periods:
        sub = nav.loc[start:end]
        if len(sub) < 2:
            continue
        ret = (sub.iloc[-1] / sub.iloc[0] - 1) * 100
        print(f"  {name:15s}: {ret:+.2f}%")


def run_backtest(prices, scores, engine: BacktestEngine, top_k=10, hold_days=5):
    """
    运行回测（兼容原接口）
    
    Args:
        prices: 价格 DataFrame
        scores: 因子得分 DataFrame
        engine: BacktestEngine 实例
        top_k: 每次选股数量
        hold_days: 持有天数
    
    Returns:
        (daily_value, trade_log)
    """
    all_dates = sorted(scores.index.get_level_values("datetime").drop_duplicates())
    all_dates = [d for d in all_dates if not pd.isna(d)]

    # 避免在拆分日执行交易
    if SPLIT_DATE_CURR in all_dates:
        cutoff_idx = all_dates.index(SPLIT_DATE_CURR)
        truncated = all_dates[:cutoff_idx]
        if len(truncated) < 2:
            print("  警告: 截断后无足够交易日")
            return [], []
        all_dates = truncated
        print(f"  ⚠️  避开拆分日 {SPLIT_DATE_CURR.date()}，回测截止至 {all_dates[-1].date()}")

    # 构建价格查找
    price_map = {}
    for (dt, inst), row in prices.iterrows():
        price_map[(dt, inst)] = {'open': row['$open'], 'close': row['$close']}

    # 构建信号
    signals = {}
    for i, date in enumerate(all_dates):
        try:
            day_scores = scores.xs(date, level="datetime")
            day_scores = day_scores.dropna()
            if len(day_scores) >= top_k:
                selected = day_scores.nlargest(top_k, 'score').index.tolist()
                signals[i] = selected
        except KeyError:
            continue

    # 运行回测
    result = engine.run(all_dates, price_map, signals, hold_days, top_k)
    return result.daily_value, result.trades


if __name__ == "__main__":
    main()
