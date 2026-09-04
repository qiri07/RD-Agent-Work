#!/usr/bin/env python3
"""
单因子回测扫描 v4 — 每个因子独立按日选 Top-K，找出胜率 Top 3
============================================================
- 加载所有 66 个因子得分
- 对每个因子：按日横截面排序，选 Top-K 股票
- 运行 5 日持有期回测，记录每笔交易盈亏
- 输出全因子排名 + Top 3 详细
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings, time
warnings.filterwarnings('ignore')

WORKSPACE = Path("git_ignore_folder/RD-Agent_workspace")
SOURCE_H5 = Path("git_ignore_folder/factor_implementation_source_data_debug/daily_pv_temp.h5")

INITIAL_CAPITAL = 1_000_000
COMMISSION = 0.0003
SLIPPAGE = 0.001
MIN_TRADE = 10_000
SPLIT_CURR = pd.Timestamp("2026-09-02")
SPLIT_PREV = pd.Timestamp("2026-09-01")
TOP_K = 10
HOLD = 5


def load_all_factors():
    """加载所有因子 → DataFrame (datetime, instrument) × factor_id"""
    factors = {}
    for d in sorted(WORKSPACE.iterdir()):
        if not d.is_dir():
            continue
        h5 = d / "result.h5"
        if not h5.exists():
            continue
        try:
            df = pd.read_hdf(h5, key="data")
            fname = df.columns[0]
            df = df.rename(columns={fname: d.name})
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
                else:
                    df.index.names = ["datetime", "instrument"]
            elif idx.names[0] != "datetime":
                df.index.names = ["datetime", "instrument"]
            df = df.ffill().fillna(0)
            df = df[~df.index.duplicated(keep='first')]
            factors[d.name] = df[d.name]
        except Exception:
            pass
    combined = pd.concat(factors, axis=1)
    combined = combined[~combined.index.duplicated(keep='first')]
    return combined


def load_prices():
    df = pd.read_hdf(SOURCE_H5, key='data')
    # 兼容不同的索引名
    if df.index.names == ['date', 'instrument']:
        df.index = df.index.set_names(['datetime', 'instrument'])
    df = df.sort_index()
    df = df[~df.index.duplicated(keep='first')]
    # 复权处理（排除 2026-09-02 的大拆分）
    try:
        prev = df.xs(SPLIT_PREV, level='datetime')['$close']
        curr = df.xs(SPLIT_CURR, level='datetime')['$close']
    except KeyError:
        return df[['$open', '$close']]
    common = prev.index.intersection(curr.index)
    ratios = prev[common] / curr[common]
    splits = ratios[ratios > 3.0].index.tolist()
    if not splits:
        return df[['$open', '$close']]
    adj = df.copy()
    mask = df.index.get_level_values('datetime') < SPLIT_CURR
    for stock in splits:
        sm = mask & (df.index.get_level_values('instrument') == stock)
        r = ratios[stock]
        for col in ['$open', '$close', '$high', '$low']:
            adj.loc[sm, col] = df.loc[sm, col] * r
    return adj[['$open', '$close']]


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


def run_backtest(price_open, price_close, dates, day_topk):
    """对单个因子的 day_topk 运行回测，返回 (trades, final_cash)"""
    cash = INITIAL_CAPITAL
    positions = {}
    trades = []
    pending = {}

    for i, d in enumerate(dates):
        # 到期卖出
        to_sell = [s for s, sd in pending.items() if sd <= i]
        for s in to_sell:
            if s in positions:
                sp = price_close.get(s, 0)
                if sp > 0:
                    tv = positions[s]['shares'] * sp
                    cash += tv * (1 - COMMISSION - SLIPPAGE)
                    pnl = (sp / positions[s]['price'] - 1) * 100
                    trades.append(pnl)
                del positions[s]
        for s in to_sell:
            pending.pop(s, None)

        # 首日无信号
        if i == 0:
            continue
        if d not in day_topk:
            continue
        selected = set(day_topk[d])

        # 调仓：卖出不在新列表中的
        for s in list(positions.keys()):
            if s not in selected:
                sp = price_close.get(s, 0)
                if sp > 0:
                    tv = positions[s]['shares'] * sp
                    cash += tv * (1 - COMMISSION - SLIPPAGE)
                    pnl = (sp / positions[s]['price'] - 1) * 100
                    trades.append(pnl)
                del positions[s]

        # 买入新标的
        if cash > MIN_TRADE:
            alloc = cash / TOP_K
            for s in selected:
                if s in positions:
                    continue
                bp = price_open.get(s, 0)
                if bp <= 0:
                    continue
                inv = min(alloc, cash * 0.99)
                if inv < MIN_TRADE:
                    continue
                sh = int(inv / bp / 100) * 100
                if sh <= 0:
                    continue
                cost = sh * bp * (1 + COMMISSION + SLIPPAGE)
                if cost > cash:
                    sh = int(cash / bp / 100) * 100
                    if sh <= 0:
                        continue
                    cost = sh * bp * (1 + COMMISSION + SLIPPAGE)
                cash -= cost
                positions[s] = {'shares': sh, 'price': bp}
                if HOLD > 0 and i + HOLD < len(dates):
                    pending[s] = i + HOLD

    # 最后平仓
    last_d = dates[-1]
    for s in list(positions.keys()):
        sp = price_close.get(s, 0)
        if sp > 0:
            tv = positions[s]['shares'] * sp
            cash += tv * (1 - COMMISSION - SLIPPAGE)
            trades.append((sp / positions[s]['price'] - 1) * 100)

    return trades, cash


def backtest_all_factors(scores_df, prices_df):
    """对每个因子独立回测，返回结果列表"""
    prices = prices_df.sort_index()
    dates = sorted(prices.index.get_level_values('datetime').drop_duplicates())
    dates = [d for d in dates if not pd.isna(d) and d < SPLIT_CURR]
    if len(dates) < 2:
        return []

    # 构建价格查找 dict
    price_open = {}
    price_close = {}
    for (dt, inst), row in prices.iterrows():
        price_open[(dt, inst)] = row['$open']
        price_close[(dt, inst)] = row['$close']

    factor_ids = list(scores_df.columns)
    results = []
    t0 = time.time()

    for fid in factor_ids:
        factor_series = scores_df[fid]
        day_topk = compute_day_topk(factor_series)
        n_valid = len(day_topk)
        if n_valid < 10:
            continue

        trades, final_cash = run_backtest(price_open, price_close, dates, day_topk)
        if not trades:
            continue

        total_ret = (final_cash / INITIAL_CAPITAL - 1) * 100
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t <= 0]
        win_rate = len(wins) / len(trades) * 100
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 1
        pf = avg_win / avg_loss if avg_loss > 0 else float('inf')

        elapsed = time.time() - t0
        print(f"  [{fid[:12]}] 胜率={win_rate:.1f}% 收益={total_ret:+.1f}%  "
              f"交易={len(trades)} 选股日={n_valid}  ({elapsed:.0f}s)", flush=True)

        results.append({
            'factor_id': fid,
            'total_return': round(total_ret, 2),
            'win_rate': round(win_rate, 1),
            'total_trades': len(trades),
            'win_trades': len(wins),
            'profit_factor': round(pf, 2),
            'final_value': round(final_cash, 0),
            'trades': trades,
        })

    return results


def main():
    print("=" * 70)
    print("  单因子回测扫描 v4 — 胜率 Top 3")
    print("=" * 70)

    print("\n📂 加载因子得分...")
    t0 = time.time()
    scores = load_all_factors()
    print(f"  {scores.shape[0]:,} 行 × {scores.shape[1]} 因子  ({time.time()-t0:.1f}s)")

    print("\n📂 加载价格数据...")
    prices = load_prices()
    print(f"  {len(prices):,} 行, {prices.index.get_level_values('instrument').nunique():,} 只")

    print(f"\n🚀 开始回测 ({scores.shape[1]} 个因子)...")
    results = backtest_all_factors(scores, prices)

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


if __name__ == "__main__":
    main()
