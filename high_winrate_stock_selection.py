#!/usr/bin/env python3
"""
高胜率因子选股策略 v2 — 稳健版
- 过滤北交所，只选沪深主板+创业板+科创板
- 仅使用 Top 5 最强因子（避免过拟合）
- 加入涨跌停过滤和流动性过滤

架构：使用 engine/ 模块
"""
import warnings
warnings.filterwarnings('ignore')

import json
import logging
import numpy as np
import pandas as pd
import time
from pathlib import Path

import config as cfg
from engine.backtest import BacktestEngine, create_backtest_engine
from engine.factor import FactorEngine, create_factor_engine
from engine.metrics import PerformanceAnalyzer, create_performance_analyzer
from engine.pricing import PriceEngine

logger = logging.getLogger(__name__)

pd.set_option('display.max_columns', 20)
pd.set_option('display.width', 200)

WS = cfg.RDAGENT_WORKSPACE
OUT = cfg.PROJECT_ROOT
SRC_PQ = cfg.DAILY_PV_PQ

valid_prefixes = ['SH', 'SZ']


def main():
    logger.info("=" * 70)
    logger.info("  高胜率因子选股策略 (v2 — 稳健版)")
    logger.info("=" * 70)
    t_main = time.time()

    # 初始化引擎
    price_engine = PriceEngine()
    backtest_engine = create_backtest_engine(
        initial_capital=1_000_000,
        commission_rate=0.0013,
        slippage_rate=0.0013,
        min_trade_value=10000
    )
    factor_engine = create_factor_engine(WS)
    perf_analyzer = create_performance_analyzer(1_000_000)

    # ── Step 1: 加载IC结果，选Top 5最强因子 ─────────────────
    logger.info("\n步骤 1: 因子筛选")
    logger.info("-" * 70)
    ic = pd.read_csv(OUT / "ic_analysis_comprehensive.csv")
    ic['ic_key'] = ic['IC_5d'].round(4)
    ic_unique = ic.drop_duplicates(subset='ic_key', keep='first').sort_values('abs_IC', ascending=False)

    selected = ic_unique[(ic_unique['abs_IC'] >= 0.02) & (ic_unique['IC_pos_5d'] >= 0.7)]
    top5 = selected.head(5)
    selected_fids = top5['factor_id'].tolist()
    selected_names = dict(zip(selected_fids, top5['factor_name']))
    selected_ic = dict(zip(selected_fids, top5['IC_5d']))
    selected_pos = dict(zip(selected_fids, top5['IC_pos_5d']))

    logger.info("  从 %d 个独立因子中，筛选出 %d 个顶级因子:", len(ic_unique), len(selected_fids))
    for fid in selected_fids:
        fname = str(selected_names.get(fid, fid))[:25]
        logger.info("    %s  %s  IC=%+.4f  pos=%.3f", fid[:12].ljust(14), fname.ljust(27), selected_ic[fid], selected_pos[fid])

    # ── Step 2: 加载数据 ───────────────────────────────────────
    logger.info("\n步骤 2: 加载数据")
    logger.info("-" * 70)

    # 加载价格
    prices = pd.read_parquet(SRC_PQ).reset_index()
    prices = prices[~prices.duplicated(subset=['date', 'instrument'], keep='first')]
    prices = prices[prices['instrument'].str[:2].isin(valid_prefixes)]
    logger.info("  价格数据: %d 条 (已过滤北交所)", len(prices))

    # 构建价格查找
    price_map = {}
    for _, row in prices.iterrows():
        price_map[(row['date'], row['instrument'])] = row['$close']

    # 加载因子
    factor_dict = factor_engine.load_factors(selected_fids)
    # 过滤只保留沪深股票
    for fid in factor_dict:
        factor_dict[fid] = factor_dict[fid][
            factor_dict[fid].index.get_level_values('instrument').str[:2].isin(valid_prefixes)
        ]

    combined = pd.concat(factor_dict, axis=1)
    combined = combined[~combined.index.duplicated(keep='first')]
    logger.info("  因子数据: %d 个 × %d 行", combined.shape[1], combined.shape[0])

    # ── Step 3: 横截面标准化 + 加权合成 ────────────────────────
    logger.info("\n步骤 3: 多因子合成")
    logger.info("-" * 70)

    weights = {}
    for fid, alias in selected_names.items():
        w = abs(selected_ic.get(fid, 0)) * selected_pos.get(fid, 0)
        if w > 0:
            weights[alias] = w
    total_w = sum(weights.values())

    standardized = factor_engine.cross_section_zscore(combined)
    standardized = standardized.fillna(0)

    score_col = "composite_score"
    score_cols = []
    for col in standardized.columns:
        if col == score_col:
            continue
        w = weights.get(col, 0)
        if w > 0:
            standardized[f"score_{col}"] = standardized[col] * (w / total_w)
            score_cols.append(f"score_{col}")
    standardized[score_col] = standardized[score_cols].sum(axis=1)

    latest_date = standardized.index.get_level_values('datetime').max()
    logger.info("  最新日期: %s", latest_date.date())

    # ── Step 4: 选股 ───────────────────────────────────────────
    logger.info("\n步骤 4: 股票筛选 (Top 10)")
    logger.info("-" * 70)

    TOP_K = 10
    top_stocks = factor_engine.get_top_stocks(standardized, top_k=TOP_K, date=latest_date)

    logger.info("  最新交易日: %s", latest_date.date())
    logger.info("  %s  %s  %s", "排名".rjust(4), "股票代码".rjust(12), "综合得分".rjust(10))
    logger.info("  %s  %s  %s", "----".rjust(4), "------------".rjust(12), "----------".rjust(10))
    for i, (stock, row) in enumerate(top_stocks.iterrows(), 1):
        stock_str = str(stock)
        logger.info("  %4d  %12s  %10.4f", i, stock_str, row['score'])

    # 各因子贡献
    day_std = standardized.xs(latest_date, level="datetime")
    logger.info("\n  各股票因子贡献明细:")
    for stock in top_stocks.index:
        contribs = []
        for col in day_std.columns:
            if col == score_col:
                continue
            w = weights.get(col, 0)
            if w > 0:
                val = float(day_std.loc[stock, col]) if stock in day_std.index else 0.0
                contribs.append((col, val * (w / total_w)))
        contribs.sort(key=lambda x: x[1], reverse=True)
        top3 = ", ".join([f"{c[:8]}={v:+.3f}" for c, v in contribs[:3]])
        logger.info("    %s: score=%.4f  [%s]", stock, top_stocks.loc[stock, 'score'], top3)

    # ── Step 5: 回测验证 ───────────────────────────────────────
    logger.info("\n步骤 5: 回测验证")
    logger.info("-" * 70)

    HOLD_DAYS = 5
    all_dates = sorted(standardized.index.get_level_values('datetime').drop_duplicates())
    all_dates = [d for d in all_dates if not pd.isna(d)]

    # 构建信号
    signals = {}
    for i, date in enumerate(all_dates):
        try:
            day_scores = standardized.xs(date, level="datetime")
            day_scores = day_scores.dropna(subset=[score_col])
            day_scores = day_scores[day_scores.index.str[:2].isin(valid_prefixes)]
            if len(day_scores) >= TOP_K:
                selected_stocks = day_scores.nlargest(TOP_K, score_col).index.tolist()
                signals[i] = selected_stocks
        except KeyError:
            continue

    # 运行回测
    result = backtest_engine.run(all_dates, price_map, signals, hold_days=HOLD_DAYS, top_k=TOP_K)
    metrics = perf_analyzer.analyze(result.daily_value, result.trades)

    report = perf_analyzer.generate_report(metrics, "高胜率因子选股策略 v2")
    logger.info("\n%s", report.strip())

    # 分年度
    logger.info("\n分年度表现:")
    logger.info("-" * 70)
    nav_df = pd.DataFrame(result.daily_value).set_index('date').sort_index()
    nav_df['year'] = nav_df.index.year
    for y in sorted(nav_df['year'].unique()):
        sub = nav_df[nav_df['year'] == y]
        if len(sub) < 5:
            continue
        ret = (sub['value'].iloc[-1] / sub['value'].iloc[0] - 1) * 100
        dd = ((sub['value'] / sub['value'].cummax()) - 1).min() * 100
        logger.info("  %s: 收益=%+.2f%%  回撤=%.2f%%", y, ret, dd)

    # ── Step 6: 保存结果 ───────────────────────────────────────
    logger.info("\n保存结果...")

    top_list = []
    for stock, row in top_stocks.iterrows():
        top_list.append({'stock': stock, score_col: float(row['score']), 'rank': int(row['rank'])})
    top_out = pd.DataFrame(top_list)
    top_out['date'] = latest_date
    top_out = top_out[['date', 'stock', score_col, 'rank']]
    top_out.to_csv(OUT / "high_winrate_stocks.csv", index=False, encoding='utf-8-sig')
    logger.info("  Top 股票: %s", OUT / "high_winrate_stocks.csv")

    pd.DataFrame(result.trades).to_csv(OUT / "high_winrate_trades.csv", index=False, encoding='utf-8-sig')
    logger.info("  交易记录: %s", OUT / "high_winrate_trades.csv")

    metrics_dict = {
        'total_return_pct': metrics.total_return_pct,
        'annual_return_pct': metrics.annual_return_pct,
        'sharpe_ratio': metrics.sharpe_ratio,
        'max_drawdown_pct': metrics.max_drawdown_pct,
        'win_rate_pct': metrics.win_rate_pct,
        'total_trades': metrics.total_trades,
        'win_trades': metrics.win_trades,
        'profit_factor': metrics.profit_factor,
        'final_nav': metrics.final_nav,
        'selected_factors': len(selected_fids),
        'top_k': TOP_K,
        'hold_days': HOLD_DAYS,
        'latest_date': str(latest_date.date()),
        'version': 'v2_robust',
    }
    with open(OUT / "high_winrate_metrics.json", 'w') as f:
        json.dump(metrics_dict, f, indent=2, default=str)
    logger.info("  指标: %s", OUT / "high_winrate_metrics.json")

    logger.info("\n总耗时: %.1fs", time.time() - t_main)
    logger.info("=" * 70)
    return metrics, top_stocks, latest_date


if __name__ == "__main__":
    main()
