#!/usr/bin/env python3
"""
高胜率因子选股策略 v3 — 稳健增强版 (使用engine模块)
改进点：
1. 因子稳定性筛选：IC变异系数 < 0.8（排除2024年过拟合因子）
2. 近期加权：2025-2026年IC权重加倍
3. 加入反转因子对冲纯动量风险
4. ICIR过滤（IC/标准差），衡量因子有效性
5. 涨跌停过滤 + 流动性过滤

架构：使用 engine/ 和 factors/ 模块
"""
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from pathlib import Path
import json
import time
import sys

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg
from engine.pricing import PriceEngine
from engine.backtest import BacktestEngine, create_backtest_engine
from engine.factor import FactorEngine, create_factor_engine
from engine.metrics import PerformanceAnalyzer, create_performance_analyzer
from factors.factor_selector import FactorSelector


def main():
    print("=" * 70)
    print("  高胜率因子选股策略 (v3 — 稳健增强版)")
    print("=" * 70)
    t_main = time.time()

    # ── 初始化引擎 ───────────────────────────────────────────────
    price_engine = PriceEngine()
    backtest_engine = create_backtest_engine(
        initial_capital=1_000_000,
        commission_rate=0.0013,
        slippage_rate=0.0,
        min_trade_value=10000,
        lot_size=100
    )
    perf_analyzer = create_performance_analyzer(1_000_000)

    TOP_K = 15
    HOLD_DAYS = 5
    OUT = cfg.PROJECT_ROOT
    WS = cfg.RDAGENT_WORKSPACE
    SRC_PQ = cfg.DAILY_PV_PQ
    valid_prefixes = ['SH', 'SZ']

    # ── Step 1: 因子筛选 ─────────────────────────────────────────
    print("\n📊 步骤 1: 因子稳定性筛选")
    print("-" * 70)

    ic = pd.read_csv(OUT / "ic_analysis_comprehensive.csv")
    yearly = pd.read_csv(OUT / "ic_analysis_yearly.csv")

    selector = FactorSelector(ic, yearly)
    factors = selector.select_v3_stable(top_n=8)

    if not factors:
        print("  ⚠️  未筛选出符合条件的因子")
        return

    selected_fids = [f.factor_id for f in factors]
    selected_names = {f.factor_id: f.factor_name for f in factors}

    print(f"\n  ✅ 筛选出 {len(selected_fids)} 个稳定因子:")
    print(f"  {'ID':<14} {'名称':<30} {'IC':>7s} {'POS':>5s} {'CV':>5s} {'ICIR':>6s}")
    print(f"  {'─'*14} {'─'*30} {'─'*7} {'─'*5} {'─'*5} {'─'*6}")
    for f in factors:
        fname = str(selected_names.get(f.factor_id, f.factor_id))[:28]
        print(f"  {f.factor_id:<14} {fname:<30} {f.ic_5d:>+7.4f} {f.ic_pos_5d:>5.3f} {f.ic_cv:>5.3f} {f.ic_ir:>6.3f}")

    # 加权IC
    weighted_ic_map = {f.factor_id: f.weighted_ic for f in factors}
    print(f"\n  📈 近期加权 IC:")
    for f in factors:
        fname = str(selected_names.get(f.factor_id, f.factor_id))[:25]
        print(f"    {f.factor_id[:12]:<14} {fname:<27} weighted_IC={f.weighted_ic:+.4f}")

    # ── Step 2: 加载数据 ─────────────────────────────────────────
    print(f"\n📂 步骤 2: 加载数据")
    print("-" * 70)

    # 加载价格
    prices = pd.read_parquet(SRC_PQ).reset_index()
    prices = prices[~prices.duplicated(subset=['date', 'instrument'], keep='first')]
    prices = prices[prices['instrument'].str[:2].isin(valid_prefixes)]
    print(f"  价格数据: {len(prices):,} 条")

    # 构建价格映射
    price_map = {}
    for _, row in prices.iterrows():
        price_map[(row['date'], row['instrument'])] = row['$close']

    # 加载因子
    factor_dict = {}
    for fid in selected_fids:
        h5 = WS / fid / "result.h5"
        if not h5.exists():
            print(f"  ⚠ {fid[:12]}: 文件不存在")
            continue
        try:
            df = pd.read_hdf(h5, key="data")
            fname = df.columns[0]
            alias = selected_names.get(fid, fname)
            df = df.rename(columns={fname: alias})
            
            # 标准化索引
            idx = df.index
            if idx.names == ["instrument", "date"]:
                df.index = pd.MultiIndex.from_tuples(
                    [(t[1], t[0]) for t in idx], names=["datetime", "instrument"]
                )
            elif idx.names == [None, None]:
                first = idx[0]
                if isinstance(first[0], str) and first[0].startswith(("SH", "SZ")):
                    df.index = pd.MultiIndex.from_tuples(
                        [(t[1], t[0]) for t in idx], names=["datetime", "instrument"]
                    )
            df = df.ffill().fillna(0)
            df = df[~df.index.duplicated(keep='first')]
            factor_dict[alias] = df[alias]
        except Exception as e:
            print(f"  ⚠ {fid[:12]}: {e}")

    combined = pd.concat(factor_dict, axis=1)
    combined = combined[~combined.index.duplicated(keep='first')]
    combined = combined[combined.index.get_level_values('instrument').str[:2].isin(valid_prefixes)]
    print(f"  因子数据: {combined.shape[1]} 个 × {combined.shape[0]:,} 行")

    # ── Step 3: 因子合成 ─────────────────────────────────────────
    print(f"\n🎯 步骤 3: 多因子合成")
    print("-" * 70)

    # 横截面Z-score标准化
    standardized = _cross_section_zscore(combined)
    standardized = standardized.fillna(0)

    # 加权合成
    weights = {f.factor_name: abs(weighted_ic_map.get(f.factor_id, 0)) for f in factors}
    total_w = sum(weights.values())
    
    score_col = "composite_score"
    score_cols = []
    for col in standardized.columns:
        w = weights.get(col, 0)
        if w > 0:
            standardized[f"score_{col}"] = standardized[col] * (w / total_w)
            score_cols.append(f"score_{col}")
    standardized[score_col] = standardized[score_cols].sum(axis=1)

    latest_date = standardized.index.get_level_values('datetime').max()
    print(f"  最新日期: {latest_date.date()}")
    print(f"  综合得分均值: {standardized[score_col].mean():.4f}")
    print(f"  综合得分标准差: {standardized[score_col].std():.4f}")

    # ── Step 4: 选股 ─────────────────────────────────────────────
    print(f"\n📋 步骤 4: 股票筛选 (Top {TOP_K})")
    print("-" * 70)

    day = standardized.xs(latest_date, level="datetime").copy()
    day[score_col] = day[score_col].astype(np.float64)
    day["rank"] = day[score_col].rank(ascending=False, method="dense")
    top_stocks = day.nlargest(TOP_K, score_col)

    print(f"\n  📅 最新交易日: {latest_date.date()}")
    print(f"\n  {'排名':>4s}  {'股票代码':>12s}  {'综合得分':>10s}  {'近5日涨跌':>10s}")
    print(f"  {'─'*4}  {'─'*12}  {'─'*10}  {'─'*10}")
    for i, (stock, row) in enumerate(top_stocks.iterrows(), 1):
        prev_key = (latest_date - pd.Timedelta(days=5), stock)
        curr_key = (latest_date, stock)
        ret_5d = ""
        if prev_key in price_map and curr_key in price_map:
            ret = (price_map[curr_key] / price_map[prev_key] - 1) * 100
            ret_5d = f"{ret:+.2f}%"
        print(f"  {i:4d}  {stock:>12s}  {row[score_col]:>10.4f}  {ret_5d:>10s}")

    # ── Step 5: 回测验证 ─────────────────────────────────────────
    print(f"\n🚀 步骤 5: 回测验证")
    print("-" * 70)

    # 构建信号
    all_dates = sorted(standardized.index.get_level_values('datetime').drop_duplicates())
    all_dates = [d for d in all_dates if not pd.isna(d)]

    signals = {}
    for i, date in enumerate(all_dates):
        try:
            day_scores = standardized.xs(date, level="datetime")
            day_scores = day_scores.dropna(subset=[score_col])
            day_scores = day_scores[day_scores.index.str[:2].isin(valid_prefixes)]
            if len(day_scores) >= TOP_K:
                selected = day_scores.nlargest(TOP_K, score_col).index.tolist()
                signals[i] = selected
        except KeyError:
            continue

    # 运行回测
    daily_value, trade_log = backtest_engine.run(
        all_dates, price_map, signals, hold_days=HOLD_DAYS, top_k=TOP_K
    )

    # 计算指标
    metrics = perf_analyzer.analyze(daily_value, trade_log)
    
    print(f"\n{'='*70}")
    print(f"  📈 回测结果 (v3 稳健增强版)")
    print(f"{'='*70}")
    print(f"  总收益率:        {metrics.total_return_pct:+.2f}%")
    print(f"  年化收益率:      {metrics.annual_return_pct:+.2f}%")
    print(f"  夏普比率:        {metrics.sharpe_ratio:.3f}")
    print(f"  最大回撤:        {metrics.max_drawdown_pct:.2f}%")
    print(f"  胜率:            {metrics.win_rate_pct:.1f}%")
    print(f"  总交易次数:      {metrics.total_trades}")
    print(f"  盈利次数:        {metrics.win_trades}")
    print(f"  盈亏比:          {metrics.profit_factor:.2f}")
    print(f"  最终净值:        {metrics.final_nav:.4f}")

    # 分年度表现
    print(f"\n📅 分年度表现:")
    print("-" * 70)
    nav_df = pd.DataFrame(daily_value).set_index('date').sort_index()
    nav_df['year'] = nav_df.index.year
    for y in sorted(nav_df['year'].unique()):
        sub = nav_df[nav_df['year'] == y]
        if len(sub) < 5:
            continue
        ret = (sub['value'].iloc[-1] / sub['value'].iloc[0] - 1) * 100
        dd = ((sub['value'] / sub['value'].cummax()) - 1).min() * 100
        dr = sub['value'].pct_change().dropna()
        sharpe_y = (dr.mean() * 252 - 0.02) / (dr.std() * np.sqrt(252)) if dr.std() > 0 else 0
        print(f"  {y}: 收益={ret:+.2f}%  回撤={dd:.2f}%  夏普={sharpe_y:.3f}")

    # ── Step 6: 保存结果 ─────────────────────────────────────────
    print(f"\n💾 保存结果...")

    # Top 股票
    top_list = []
    for stock, row in top_stocks.iterrows():
        top_list.append({
            'stock': stock, 
            score_col: float(row[score_col]), 
            'rank': int(row['rank'])
        })
    top_out = pd.DataFrame(top_list)
    top_out['date'] = latest_date
    top_out = top_out[['date', 'stock', score_col, 'rank']]
    top_out.to_csv(OUT / "high_winrate_stocks_v3.csv", index=False, encoding='utf-8-sig')
    print(f"  Top 股票: {OUT / 'high_winrate_stocks_v3.csv'}")

    # 交易记录
    pd.DataFrame(trade_log).to_csv(OUT / "high_winrate_trades_v3.csv", index=False, encoding='utf-8-sig')
    print(f"  交易记录: {OUT / 'high_winrate_trades_v3.csv'}")

    # 指标
    metrics_dict = {
        'total_return_pct': round(metrics.total_return_pct, 2),
        'annual_return_pct': round(metrics.annual_return_pct, 2),
        'sharpe_ratio': round(metrics.sharpe_ratio, 3),
        'max_drawdown_pct': round(metrics.max_drawdown_pct, 2),
        'win_rate_pct': round(metrics.win_rate_pct, 1),
        'total_trades': metrics.total_trades,
        'win_trades': metrics.win_trades,
        'profit_factor': round(metrics.profit_factor, 2),
        'final_nav': round(metrics.final_nav, 4),
        'selected_factors': len(selected_fids),
        'top_k': TOP_K,
        'hold_days': HOLD_DAYS,
        'latest_date': str(latest_date.date()),
        'version': 'v3_stable',
    }
    with open(OUT / "high_winrate_metrics_v3.json", 'w') as f:
        json.dump(metrics_dict, f, indent=2, default=str)
    print(f"  指标: {OUT / 'high_winrate_metrics_v3.json'}")

    print(f"\n总耗时: {time.time()-t_main:.1f}s")
    print("=" * 70)
    return metrics_dict, top_stocks, latest_date


def _cross_section_zscore(df: pd.DataFrame) -> pd.DataFrame:
    """横截面Z-score标准化"""
    result = pd.DataFrame(index=df.index, columns=df.columns, dtype=np.float64)
    for col in df.columns:
        series = df[col]
        grouped = series.groupby(level="datetime", sort=False)
        mean = grouped.transform('mean')
        std = grouped.transform('std')
        result[col] = (series - mean) / std.replace(0, np.nan)
    return result


if __name__ == "__main__":
    main()
