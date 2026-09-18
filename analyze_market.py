#!/usr/bin/env python3
from __future__ import annotations
"""
全市场股票批量分析 v4 — 纯numpy高效版
======================================
对全部 ~5,240 只股票进行：
  1. 基础收益统计
  2. 8个核心因子计算
  3. IC 检验（Spearman）
  4. 回测（5种策略）
  5. 飞书推送

注意: 核心计算逻辑已迁移到 analyze_market/ 子包，
      本模块保留 main() 作为入口。
"""
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path
import json
import time
from datetime import datetime

import config as cfg
from feishu_notify import send_feishu

# Import from submodules (backward compatible aliases)
from analyze_market.factors import compute_all_factors_np, compute_forward_ret_np
from analyze_market.stats import stock_stats_np, ic_numpy
from analyze_market.backtest import backtest_np, STRATEGIES, COL_MAP

SRC_PQ = cfg.DAILY_PV_FULL_PQ
INITIAL_CAPITAL = cfg.BACKTEST_INITIAL_CAPITAL
COMMISSION = cfg.BACKTEST_COMMISSION_RATE
SLIPPAGE = cfg.BACKTEST_SLIPPAGE_RATE
OUT_DIR = Path('outputs/market_analysis')
OUT_DIR.mkdir(parents=True, exist_ok=True)

FACTOR_COLS = ['momentum_5d','momentum_10d','momentum_20d','momentum_60d',
               'reversal_5d','rsi_14','bollinger_pos','volume_ratio']


def main():
    t_main = time.time()
    print("=" * 70, flush=True)
    print("  全市场股票批量分析 v4 (纯numpy高效版)", flush=True)
    print("=" * 70, flush=True)

    # 1. 加载数据
    print("\n[1/5] 加载数据...", flush=True)
    t0 = time.time()
    df = pd.read_parquet(SRC_PQ)
    print(f"  耗时: {time.time()-t0:.1f}s, 形状: {df.shape}", flush=True)

    instruments = sorted(df.index.get_level_values('instrument').unique().tolist())
    print(f"  股票数: {len(instruments):,}", flush=True)

    # 2. 提取每只股票的numpy数组
    print("\n[2/5] 提取股票数组...", flush=True)
    t0 = time.time()

    stock_data = {}
    df_reset = df.reset_index()

    for ticker in instruments:
        mask = df_reset['instrument'] == ticker
        sub = df_reset[mask].sort_values('date')
        dates = sub['date'].values
        close = sub['$close'].values.astype(np.float64)
        volume = sub['$volume'].values.astype(np.float64)
        if len(close) >= 200:
            stock_data[ticker] = {'dates': dates, 'close': close, 'volume': volume}

    print(f"  提取完成: {len(stock_data)} stocks, 耗时 {time.time()-t0:.1f}s", flush=True)

    # 3. 计算因子和IC
    print("\n[3/5] 计算因子 & IC & 回测...", flush=True)
    t0 = time.time()

    results = []
    errors_count = 0
    n = len(instruments)

    for i, ticker in enumerate(instruments):
        if ticker not in stock_data:
            continue

        sd = stock_data[ticker]
        close_arr = sd['close']
        dates_arr = sd['dates']
        volume_arr = sd['volume']

        try:
            # 统计
            s_stats = stock_stats_np(close_arr, dates_arr)
            if s_stats is None:
                continue

            # 因子计算
            facs = compute_all_factors_np(close_arr, volume_arr)
            fr_arr = compute_forward_ret_np(close_arr)

            # IC
            ic_list = []
            for fname in FACTOR_COLS:
                f_vals = facs[fname]
                ic_res = ic_numpy(f_vals, fr_arr)
                if ic_res:
                    ic_res['factor'] = fname
                    ic_list.append(ic_res)

            # 回测
            bt_results = []
            for strat in STRATEGIES:
                fc = COL_MAP[strat]
                if fc not in facs:
                    continue
                bt = backtest_np(close_arr, facs[fc], strat)
                if bt:
                    bt_results.append(bt)

            results.append({
                'ticker': ticker,
                'n_days': s_stats['n_days'],
                'price_min': s_stats['price_min'],
                'price_max': s_stats['price_max'],
                'ann_return_pct': s_stats['ann_return_pct'],
                'ann_volatility_pct': s_stats['ann_volatility_pct'],
                'sharpe': s_stats['sharpe'],
                'max_drawdown_pct': s_stats['max_drawdown_pct'],
                'yearly': s_stats['yearly'],
                'factor_ic': ic_list,
                'backtest_results': bt_results,
            })

        except Exception as e:
            errors_count += 1
            if errors_count <= 5:
                print(f"  ⚠️ {ticker}: {str(e)[:100]}", flush=True)

        if (i + 1) % 500 == 0 or (i + 1) == n:
            elapsed = time.time() - t0
            eta = elapsed / (i+1) * (n - i - 1) if i > 0 else 0
            print(f"  [{i+1:,}/{n:,}] ({(i+1)/n*100:.0f}%) 成功 {len(results)} 失败 {errors_count} | "
                  f"已用 {elapsed:.0f}s 剩余 ~{eta:.0f}s", flush=True)

    print(f"  分析总耗时: {time.time()-t0:.0f}s", flush=True)

    # 4. 汇总
    print("\n[4/5] 生成汇总...", flush=True)
    successful = results
    print(f"  有效: {len(successful)}, 失败: {errors_count}", flush=True)

    rets = np.array([r['ann_return_pct'] for r in successful])
    sharpes = np.array([r['sharpe'] for r in successful])
    vols = np.array([r['ann_volatility_pct'] for r in successful])
    mdds = np.array([r['max_drawdown_pct'] for r in successful])

    summary = {
        'total_stocks': len(instruments),
        'analyzed': len(successful),
        'failed': errors_count,
        'return': {
            'mean': round(float(np.nanmean(rets)), 2),
            'median': round(float(np.nanmedian(rets)), 2),
            'std': round(float(np.nanstd(rets)), 2),
            'min': round(float(np.nanmin(rets)), 2),
            'max': round(float(np.nanmax(rets)), 2),
            'positive': int((rets > 0).sum()),
            'negative': int((rets < 0).sum()),
        },
        'sharpe': {
            'mean': round(float(np.nanmean(sharpes)), 3),
            'positive': int((sharpes > 0).sum()),
        },
        'volatility': {
            'mean': round(float(np.nanmean(vols)), 2),
            'median': round(float(np.nanmedian(vols)), 2),
        },
        'drawdown': {
            'mean': round(float(np.nanmean(mdds)), 2),
            'worst': round(float(np.nanmin(mdds)), 2),
        },
    }

    by_ret = sorted(successful, key=lambda x: x['ann_return_pct'], reverse=True)
    by_sharpe = sorted(successful, key=lambda x: x['sharpe'], reverse=True)
    summary['top_return'] = [(r['ticker'], r['ann_return_pct']) for r in by_ret[:10]]
    summary['bottom_return'] = [(r['ticker'], r['ann_return_pct']) for r in by_ret[-10:]]
    summary['top_sharpe'] = [(r['ticker'], r['sharpe']) for r in by_sharpe[:10]]
    summary['worst_dd'] = [(r['ticker'], r['max_drawdown_pct']) for r in
                           sorted(successful, key=lambda x: x['max_drawdown_pct'])[:10]]

    all_ics = {}
    for r in successful:
        for ic in r.get('factor_ic', []):
            all_ics.setdefault(ic['factor'], []).append(ic['IC'])
    summary['factor_ic'] = {
        k: {
            'mean': round(float(np.mean(v)), 4),
            'pos': round(float((np.array(v) > 0).mean()), 4),
            'n': len(v),
        }
        for k, v in all_ics.items()
    }

    bt_sum = {}
    for name in STRATEGIES:
        rets_bt = [
            bt['return_pct']
            for r in successful
            for bt in r.get('backtest_results', [])
            if bt['strategy'] == name
        ]
        if rets_bt:
            a = np.array(rets_bt)
            bt_sum[name] = {
                'mean': round(float(np.mean(a)), 2),
                'pos_pct': round(float((a > 0).mean() * 100), 1),
                'best': round(float(np.max(a)), 2),
                'worst': round(float(np.min(a)), 2),
                'n': len(a),
            }
    summary['backtest'] = bt_sum
    summary['timestamp'] = datetime.now().isoformat()

    with open(OUT_DIR / 'market_analysis_all.json', 'w') as f:
        json.dump(successful, f, ensure_ascii=False, default=str, indent=2)
    with open(OUT_DIR / 'market_analysis_summary.json', 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    pd.DataFrame(
        [{'ticker': t, 'return': r} for t, r in summary['top_return']]
    ).to_csv(OUT_DIR / 'top_stocks.csv', index=False)
    print(f"  💾 结果已保存至 {OUT_DIR}", flush=True)

    # 5. 飞书推送
    print("\n[5/5] 推送飞书...", flush=True)
    try:
        lines = []
        lines.append(f"📊 全市场股票分析报告")
        lines.append(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"📁 数据源: daily_pv_full.parquet")
        lines.append("")
        lines.append(f"📈 股票总数: {summary['analyzed']} 只")
        lines.append(f"✅ 盈利: {summary['return']['positive']} 只 "
                     f"({summary['return']['positive']/summary['analyzed']*100:.1f}%)")
        lines.append(f"📉 亏损: {summary['return']['negative']} 只")
        lines.append(f"📊 平均收益: {summary['return']['mean']:+.1f}% | "
                     f"中位数: {summary['return']['median']:+.1f}%")
        lines.append(f"⚡ 平均波动: {summary['volatility']['mean']:.1f}%")
        lines.append(f"📉 平均回撤: {summary['drawdown']['mean']:.1f}%")
        lines.append("")
        lines.append(f"🏆 收益 Top 10:")
        for i, (t, r) in enumerate(summary['top_return'], 1):
            lines.append(f"  {i:2d}. {t}  {r:+.1f}%")
        lines.append("")
        lines.append(f"⚠️ 亏损 Top 5:")
        for i, (t, r) in enumerate(summary['bottom_return'][:5], 1):
            lines.append(f"  {i}. {t}  {r:+.1f}%")
        lines.append("")
        lines.append(f"📊 夏普 Top 5:")
        for i, (t, sp) in enumerate(summary['top_sharpe'][:5], 1):
            lines.append(f"  {i}. {t}  夏普={sp:+.2f}")
        lines.append("")
        lines.append(f"🔬 因子 IC 均值（按 |IC| 排序）:")
        for fname, fs in sorted(summary['factor_ic'].items(),
                                 key=lambda x: abs(x[1]['mean']), reverse=True):
            lines.append(f"  {fname:<18s}  IC={fs['mean']:+.4f}  "
                         f"正占比={fs['pos']*100:.0f}%")
        lines.append("")
        lines.append(f"🎯 回测策略表现:")
        for name, bs in sorted(summary['backtest'].items()):
            lines.append(f"  {name:<18s}  平均收益={bs['mean']:+.1f}%  "
                         f"盈利比例={bs['pos_pct']:.0f}%  "
                         f"最佳={bs['best']:+.1f}%")
        lines.append("")
        lines.append(f"💾 完整结果: outputs/market_analysis/")
        lines.append(f"⏱  总耗时: {time.time()-t_main:.0f}s")

        msg = "\n".join(lines)
        send_feishu(msg)
        print("  ✅ 飞书推送成功", flush=True)
    except Exception as e:
        print(f"  ⚠️ 飞书推送失败: {e}", flush=True)

    print(f"\n{'='*70}", flush=True)


if __name__ == '__main__':
    main()
