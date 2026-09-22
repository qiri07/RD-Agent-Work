#!/usr/bin/env python3
from __future__ import annotations

"""
白名单股票完整流水线
=====================
对白名单股票进行：因子计算 → IC分析 → 选股回测 → 结果推送飞书
每个阶段完成后即时推送飞书通知。

用法:
    python3 whitelist_pipeline.py                  # 完整流程
    python3 whitelist_pipeline.py --phase ic-only  # 只跑 IC 分析
    python3 whitelist_pipeline.py --phase bt-only  # 只跑回测
"""
import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from engine.backtest import BacktestEngine
from engine.factor_compute import load_whitelist_data, compute_factors, compute_ic, synthesize_score, FACTOR_NAMES
from engine.metrics import PerformanceAnalyzer
from engine.pricing import PriceEngine
from feishu_notify import send_feishu

BASE = cfg.PROJECT_ROOT
WHITELIST = cfg.WHITELIST_STOCKS

BACKTEST_TOP_K = 10
BACKTEST_HOLD_DAYS = 5
INITIAL_CAPITAL = cfg.BACKTEST_INITIAL_CAPITAL


# ─── Phase 1: 因子计算 ───────────────────────────────────────────────────────

def push_factor_results(factors_df: pd.DataFrame) -> bool:
    """推送因子计算结果到飞书"""
    factor_names = list(factors_df.columns)
    total_vals = sum(factors_df[f].dropna().shape[0] for f in factor_names)
    date_range = (factors_df.index.get_level_values('datetime').min().date(),
                  factors_df.index.get_level_values('datetime').max().date())
    n_inst = factors_df.index.get_level_values('instrument').nunique()

    lines = [
        "✅ **白名单因子计算完成**",
        f"📋 白名单: {n_inst} 只股票 ({', '.join(WHITELIST[:10])}{'...' if n_inst > 10 else ''})",
        f"📅 日期范围: {date_range[0]} ~ {date_range[1]}",
        f"🧮 因子数: {len(factor_names)} 个",
        f"📊 总有效值: {total_vals:,} 条",
        "",
        "**因子统计:**",
    ]
    for fname in factor_names:
        valid = int(factors_df[fname].dropna().shape[0])
        non_zero = int((factors_df[fname] != 0).sum())
        lines.append(f"  • {fname}: {valid:,} 有效值, {non_zero:,} 非零")

    lines += [
        "",
        "💾 保存: whitelist_factors.parquet",
        f"📅 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return send_feishu("\n".join(lines))


# ─── Phase 2: IC 分析 ────────────────────────────────────────────────────────

def push_ic_results(ic_df: pd.DataFrame) -> bool:
    """推送 IC 分析结果到飞书"""
    lines = [
        "📊 **白名单 IC 分析完成**",
        f"📋 白名单: {len(WHITELIST)} 只股票",
        f"🧮 分析因子: {len(ic_df)} 个",
        f"📅 有效交易日: {int(ic_df['n_days'].mean())} 天",
        f"平均 |IC|:  {ic_df['IC_5d'].abs().mean():.4f}",
        "",
        "**Top 5 因子:**",
    ]
    for rank, (_, row) in enumerate(ic_df.head(5).iterrows(), 1):
        icon = "🟢" if row['IC_5d'] > 0 else "🔴"
        lines.append(
            f"  {icon} #{rank} {row['factor_id']}  "
            f"IC={row['IC_5d']:+.4f}  t={row['IC_t_5d']:.2f}  "
            f"正占比={row['IC_pos_5d']:.1%}"
        )

    lines += ["", "**底部 5 因子:**"]
    for rank, (_, row) in enumerate(ic_df.tail(5).iterrows(), 1):
        icon = "🟢" if row['IC_5d'] > 0 else "🔴"
        lines.append(
            f"  {icon} #{len(ic_df)-4+rank-5} {row['factor_id']}  "
            f"IC={row['IC_5d']:+.4f}  t={row['IC_t_5d']:.2f}"
        )

    lines += [
        "",
        "💾 保存: whitelist_ic_results.csv",
        f"📅 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return send_feishu("\n".join(lines))


# ─── Phase 3: 选股 ───────────────────────────────────────────────────────────

def run_stock_selection(factors_df: pd.DataFrame, ic_df: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
    """基于 IC 结果对白名单股票进行选股"""
    print("\n🎯 白名单选股...", flush=True)

    valid_factors = ic_df[ic_df['IC_5d'].abs() >= 0.005]['factor_id'].tolist()
    if len(valid_factors) >= 3:
        top_factors = ic_df.loc[ic_df['IC_5d'].abs().nlargest(5).index, 'factor_id'].tolist()
    else:
        top_factors = ic_df.head(3)['factor_id'].tolist()

    print(f"  使用因子: {top_factors}", flush=True)

    all_dates = sorted(factors_df.index.get_level_values('datetime').unique())
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
        except Exception:  # noqa: BLE001,S112
            continue

    print(f"  生成信号: {len(signals)} 个交易日", flush=True)

    rows = []
    for idx, stocks in signals.items():
        date = all_dates[idx]
        for rank, inst in enumerate(stocks, 1):
            rows.append({'date': date, 'instrument': inst, 'rank': rank})
    return pd.DataFrame(rows)


def push_stock_results(stocks_df: pd.DataFrame) -> bool:
    """推送选股结果到飞书"""
    if stocks_df.empty:
        return send_feishu("⚠️ 白名单选股结果为空")

    latest_date = stocks_df['date'].max()
    latest_stocks = stocks_df[stocks_df['date'] == latest_date].head(10)

    lines = [
        "🎯 **白名单选股结果**",
        f"📅 最新日期: {latest_date}",
        f"📋 白名单: {len(WHITELIST)} 只股票",
        "",
        f"**Top 10 选股 ({latest_date}):**",
    ]
    for _, row in latest_stocks.iterrows():
        lines.append(f"  #{int(row['rank'])}  {row['instrument']}")

    lines += [
        "",
        f"💡 共 {len(stocks_df['instrument'].unique())} 只不同股票被选中",
        "💾 保存: whitelist_stocks_selection.csv",
        f"📅 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return send_feishu("\n".join(lines))


# ─── Phase 4: 回测 ───────────────────────────────────────────────────────────

def run_backtest(df: pd.DataFrame, factors_df: pd.DataFrame, ic_df: pd.DataFrame,
                 top_k: int = 10, hold_days: int = 5) -> tuple:
    """运行白名单回测"""
    print("\n🚀 运行白名单回测...", flush=True)

    valid_factors = ic_df[ic_df['IC_5d'].abs() >= 0.005]['factor_id'].tolist()
    if len(valid_factors) >= 3:
        top_factors = ic_df.loc[ic_df['IC_5d'].abs().nlargest(5).index, 'factor_id'].tolist()
    else:
        top_factors = ic_df.head(3)['factor_id'].tolist()

    print(f"  使用因子: {top_factors}", flush=True)

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
        except Exception:  # noqa: BLE001,S112
            continue

    print(f"  生成信号: {len(signals)} 个交易日", flush=True)

    price_engine = PriceEngine()
    price_map = price_engine.build_price_map(df)

    bt_engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
    result = bt_engine.run(all_dates, price_map, signals, hold_days, top_k)

    analyzer = PerformanceAnalyzer(initial_capital=INITIAL_CAPITAL)
    metrics = analyzer.analyze(result.daily_value, result.trades)

    print(f"\n{'='*60}", flush=True)
    print("  回测结果", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  回测天数:           {metrics.total_days}", flush=True)
    print(f"  初始资金:           {INITIAL_CAPITAL:,.0f} 元", flush=True)
    print(f"  最终净值:           {metrics.final_value:,.0f} 元", flush=True)
    print(f"  总收益率:           {metrics.total_return_pct:+.2f}%", flush=True)
    print(f"  年化收益率:         {metrics.annual_return_pct:+.2f}%", flush=True)
    print(f"  夏普比率:           {metrics.sharpe_ratio:.3f}", flush=True)
    print(f"  最大回撤:           {metrics.max_drawdown_pct:.2f}%", flush=True)
    print(f"  胜率:               {metrics.win_rate_pct:.1f}%", flush=True)
    print(f"  总交易次数:         {metrics.total_trades}", flush=True)
    print(f"  盈利交易:           {metrics.win_trades}", flush=True)
    print(f"  盈亏比:             {metrics.profit_factor:.2f}", flush=True)
    print(f"{'='*60}", flush=True)

    return metrics, result


def push_backtest_results(metrics, result) -> bool:
    """推送回测结果到飞书"""
    nav_df = pd.DataFrame(result.daily_value)
    trades_df = pd.DataFrame(result.trades)

    nav_df.to_csv(BASE / "whitelist_backtest_nav.csv", index=False)
    trades_df.to_csv(BASE / "whitelist_backtest_trades.csv", index=False)

    lines = [
        "📈 **白名单回测结果**",
        f"📋 白名单: {len(WHITELIST)} 只股票",
        f"💰 初始资金: {INITIAL_CAPITAL:,.0f} 元",
        "",
        "**收益指标:**",
        f"  最终净值: {metrics.final_value:,.0f} 元",
        f"  总收益率: {metrics.total_return_pct:+.2f}%",
        f"  年化收益率: {metrics.annual_return_pct:+.2f}%",
        "",
        "**风险指标:**",
        f"  夏普比率: {metrics.sharpe_ratio:.3f}",
        f"  最大回撤: {metrics.max_drawdown_pct:.2f}%",
        "",
        "**交易统计:**",
        f"  回测天数: {metrics.total_days}",
        f"  总交易次数: {metrics.total_trades}",
        f"  胜率: {metrics.win_rate_pct:.1f}%",
        f"  盈利交易: {metrics.win_trades}/{metrics.total_trades}",
        f"  盈亏比: {metrics.profit_factor:.2f}",
        "",
        "💾 保存文件:",
        "  - whitelist_backtest_nav.csv",
        "  - whitelist_backtest_trades.csv",
        f"📅 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return send_feishu("\n".join(lines))


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="白名单股票完整流水线")
    parser.add_argument("--phase", choices=["all", "factor", "ic", "select", "backtest"],
                        default="all", help="指定运行阶段")
    args = parser.parse_args()

    if not cfg.is_whitelist_configured():
        print("❌ 白名单未配置，请在 .env 文件中设置 WHITELIST_STOCKS", flush=True)
        print("   示例: WHITELIST_STOCKS=SH600000,SH600001,SZ000001", flush=True)
        return 1

    t_start = time.time()
    print("=" * 70, flush=True)
    print(f"  白名单股票完整流水线 — {len(WHITELIST)} 只股票", flush=True)
    print("=" * 70, flush=True)
    print(f"  白名单: {', '.join(WHITELIST[:8])}{'...' if len(WHITELIST) > 8 else ''}", flush=True)

    # Phase 1: 因子计算
    df = None
    factors_df = None
    ic_df = None
    metrics = None
    result = None

    if args.phase in ["all", "factor"]:
        print("\n" + "=" * 70, flush=True)
        print("  Phase 1: 因子计算", flush=True)
        print("=" * 70, flush=True)
        t0 = time.time()
        df = load_whitelist_data()
        factors_df = compute_factors(df)
        factors_df.to_parquet(BASE / "whitelist_factors.parquet")
        print(f"  ✅ 因子计算完成 ({time.time()-t0:.1f}s)", flush=True)
        print("  💾 保存: whitelist_factors.parquet", flush=True)
        push_factor_results(factors_df)

    # Phase 2: IC 分析
    if args.phase in ["all", "ic"]:
        if factors_df is None:
            print("  ⚠️  因子数据未加载，重新加载...", flush=True)
            df = load_whitelist_data()
            factors_df = compute_factors(df)
        t0 = time.time()
        ic_df = compute_ic(factors_df, df)
        ic_df.to_csv(BASE / "whitelist_ic_results.csv", index=False)
        print(f"  ✅ IC 分析完成 ({time.time()-t0:.1f}s)", flush=True)
        print("  💾 保存: whitelist_ic_results.csv", flush=True)
        push_ic_results(ic_df)

    # Phase 3: 选股
    if args.phase in ["all", "select"]:
        if ic_df is None:
            print("  ⚠️  IC 结果未加载，跳过选股", flush=True)
        else:
            t0 = time.time()
            stocks_df = run_stock_selection(factors_df, ic_df, top_k=BACKTEST_TOP_K)
            stocks_df.to_csv(BASE / "whitelist_stocks_selection.csv", index=False)
            print(f"  ✅ 选股完成 ({time.time()-t0:.1f}s)", flush=True)
            push_stock_results(stocks_df)

    # Phase 4: 回测
    if args.phase in ["all", "backtest"]:
        if ic_df is None:
            print("  ⚠️  IC 结果未加载，跳过回测", flush=True)
        else:
            t0 = time.time()
            metrics, result = run_backtest(df, factors_df, ic_df,
                                           top_k=BACKTEST_TOP_K,
                                           hold_days=BACKTEST_HOLD_DAYS)
            print(f"  ✅ 回测完成 ({time.time()-t0:.1f}s)", flush=True)
            push_backtest_results(metrics, result)

    # 汇总
    summary = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'duration_s': time.time() - t_start,
        'n_stocks': len(WHITELIST),
        'n_factors': len(factors_df.columns) if factors_df is not None else 0,
        'n_ic_factors': len(ic_df) if ic_df is not None else 0,
        'total_return_pct': metrics.total_return_pct if metrics is not None else None,
    }
    with open(BASE / "whitelist_pipeline_summary.json", 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*70}", flush=True)
    print("  流水线完成! 总耗时: " + f"{time.time()-t_start:.1f}s", flush=True)
    print("  汇总: whitelist_pipeline_summary.json", flush=True)
    print(f"{'='*70}", flush=True)

    # 推送最终汇总
    summary_lines = [
        "✅ **白名单流水线完成**",
        f"📋 股票数: {len(WHITELIST)}",
        f"🧮 因子数: {summary['n_factors']}",
        f"📊 IC 因子: {summary['n_ic_factors']}",
        f"⏱ 总耗时: {summary['duration_s']:.1f}s",
        f"📅 完成时间: {summary['timestamp']}",
    ]
    if metrics is not None:
        summary_lines.insert(4, f"💰 总收益率: {metrics.total_return_pct:+.2f}%")
        summary_lines.insert(4, f"📈 年化收益: {metrics.annual_return_pct:+.2f}%")
        summary_lines.insert(4, f"🛡 最大回撤: {metrics.max_drawdown_pct:.2f}%")
    summary_lines += [
        "",
        "💾 输出文件:",
        "  - whitelist_factors.parquet",
        "  - whitelist_ic_results.csv",
        "  - whitelist_stocks_selection.csv",
        "  - whitelist_backtest_nav.csv",
        "  - whitelist_backtest_trades.csv",
        "  - whitelist_pipeline_summary.json",
    ]
    send_feishu("\n".join(summary_lines))

    return 0


if __name__ == "__main__":
    sys.exit(main())
