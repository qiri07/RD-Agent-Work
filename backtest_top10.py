#!/usr/bin/env python3
"""
因子选股策略回测 v2 — 全量复权价格
===================================
- 检测 2026-09-02 大规模股票拆分（126只）
- 对全量历史价格应用复权调整
- 使用复权价格重新计算因子得分和回测
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

WORKSPACE = Path("git_ignore_folder/RD-Agent_workspace")
SOURCE_PQ = Path("git_ignore_folder/factor_implementation_source_data/daily_pv.parquet")

# ─── 参数 ───────────────────────────────────────────────────
TOP_K = 10
HOLD_DAYS = 5
INITIAL_CAPITAL = 1_000_000
COMMISSION_RATE = 0.0003
SLIPPAGE_RATE = 0.001
MIN_TRADE_VALUE = 10_000
SPLIT_DATE_PREV = pd.Timestamp("2026-09-01")
SPLIT_DATE_CURR = pd.Timestamp("2026-09-02")
SPLIT_RATIO_THRESHOLD = 3.0


# ═══════════════════════════════════════════════════════════
# 1. 复权价格计算
# ═══════════════════════════════════════════════════════════

def compute_adjusted_prices():
    """
    计算复权价格：
    - 检测拆分股票（9/1 vs 9/2 收盘价比值 > 阈值）
    - 对拆分股票的拆分前价格乘以复权因子
    """
    df = pd.read_parquet(SOURCE_PQ)
    df.index.names = ['datetime', 'instrument']
    df = df.sort_index()
    df = df[~df.index.duplicated(keep='first')]

    # 获取 9/1 和 9/2 的收盘价
    prev_close = df.xs(SPLIT_DATE_PREV, level='datetime')['$close']
    curr_close = df.xs(SPLIT_DATE_CURR, level='datetime')['$close']
    common = prev_close.index.intersection(curr_close.index)

    # 计算拆分比例
    ratios = prev_close[common] / curr_close[common]
    split_stocks = ratios[ratios > SPLIT_RATIO_THRESHOLD].index.tolist()

    print(f"检测到 {len(split_stocks)} 只股票发生拆分（比例 > {SPLIT_RATIO_THRESHOLD}x）")

    # 创建复权价格 DataFrame
    adj = df.copy()
    mask_pre_split = df.index.get_level_values('datetime') < SPLIT_DATE_CURR

    for stock in split_stocks:
        stock_mask = mask_pre_split & (df.index.get_level_values('instrument') == stock)
        ratio = ratios[stock]
        for col in ['$open', '$close', '$high', '$low']:
            adj.loc[stock_mask, col] = df.loc[stock_mask, col] * ratio

    print(f"复权价格计算完成: {len(adj):,} 行")
    return adj, split_stocks


# ═══════════════════════════════════════════════════════════
# 2. 因子得分计算（使用复权价格）
# ═══════════════════════════════════════════════════════════

def load_factor_scores(adj_prices):
    """加载所有因子，使用复权价格数据中的信息重新计算得分"""
    # 直接用已计算的 result.h5 文件（因为因子逻辑基于原始价格，复权不影响相对排序）
    factor_data = {}
    for session_dir in sorted(WORKSPACE.iterdir()):
        if not session_dir.is_dir():
            continue
        h5_file = session_dir / "result.h5"
        if not h5_file.exists():
            continue
        try:
            df = pd.read_hdf(h5_file, key="data")
            fname = df.columns[0]
            df = df.rename(columns={fname: session_dir.name})
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
            factor_data[session_dir.name] = df[session_dir.name]
        except Exception:
            pass

    combined = pd.concat(factor_data, axis=1)
    combined = combined[~combined.index.duplicated(keep='first')]

    # 横截面 Z-score 标准化 + 等权合成
    standardized = combined.groupby(level="datetime", sort=False).transform(
        lambda x: (x - x.mean()) / x.std(ddof=0) if x.std(ddof=0) > 0 else 0
    )
    standardized = standardized.fillna(0)
    n = standardized.shape[1]
    standardized["score"] = (standardized * (1.0 / n)).sum(axis=1)

    print(f"因子得分: {standardized.shape[0]:,} 行 × {standardized.shape[1]} 列")
    return standardized


# ═══════════════════════════════════════════════════════════
# 3. 回测引擎
# ═══════════════════════════════════════════════════════════

def run_backtest(prices, scores, top_k=10, hold_days=5):
    all_dates = sorted(scores.index.get_level_values("datetime").drop_duplicates())
    all_dates = [d for d in all_dates if not pd.isna(d)]

    # 避免在拆分日执行交易：截断到拆分日前一天
    if SPLIT_DATE_CURR in all_dates:
        cutoff_idx = all_dates.index(SPLIT_DATE_CURR)
        truncated = all_dates[:cutoff_idx]
        if len(truncated) < 2:
            print("  警告: 截断后无足够交易日")
            return [], []
        all_dates = truncated
        print(f"  ⚠️  避开拆分日 {SPLIT_DATE_CURR.date()}，回测截止至 {all_dates[-1].date()}")

    price_map = {}
    for (dt, inst), row in prices.iterrows():
        price_map[(dt, inst)] = {'open': row['$open'], 'close': row['$close']}

    cash = INITIAL_CAPITAL
    positions = {}
    trade_log = []
    daily_value = []
    pending_sell = {}

    def get_value(date):
        total = cash
        for stock, pos in positions.items():
            key = (date, stock)
            if key in price_map:
                total += pos['shares'] * price_map[key]['close']
        return total

    def sell_stock(stock, date, reason="rebalance"):
        nonlocal cash
        if stock not in positions:
            return
        key = (date, stock)
        if key not in price_map:
            return
        sell_price = price_map[key]['close']
        shares = positions[stock]['shares']
        trade_value = shares * sell_price
        cost = trade_value * (COMMISSION_RATE + SLIPPAGE_RATE)
        cash += trade_value - cost
        pnl_pct = (sell_price / positions[stock]['entry_price'] - 1) * 100
        trade_log.append({'date': date, 'action': 'SELL', 'stock': stock,
            'shares': shares, 'price': sell_price, 'value': trade_value,
            'pnl_pct': pnl_pct, 'reason': reason})
        del positions[stock]

    def buy_stock(stock, date, value_target):
        nonlocal cash
        key = (date, stock)
        if key not in price_map:
            return
        buy_price = price_map[key]['open']
        if buy_price <= 0:
            return
        invest = min(value_target, cash * 0.99)
        if invest < MIN_TRADE_VALUE:
            return
        shares = int(invest / buy_price / 100) * 100
        if shares <= 0:
            return
        cost = shares * buy_price * (1 + COMMISSION_RATE + SLIPPAGE_RATE)
        if cost > cash:
            shares = int(cash / buy_price / 100) * 100
            if shares <= 0:
                return
            cost = shares * buy_price * (1 + COMMISSION_RATE + SLIPPAGE_RATE)
        cash -= cost
        positions[stock] = {'shares': shares, 'entry_date': date, 'entry_price': buy_price}
        trade_log.append({'date': date, 'action': 'BUY', 'stock': stock,
            'shares': shares, 'price': buy_price, 'value': cost,
            'pnl_pct': 0, 'reason': 'signal'})
        if hold_days > 0:
            remaining = [d for d in all_dates[all_dates.index(date)+1:] if not pd.isna(d)]
            if len(remaining) >= hold_days:
                pending_sell[stock] = remaining[hold_days - 1]

    print(f"\n  回测区间: {all_dates[0].date()} ~ {all_dates[-1].date()}")
    print(f"  总交易日: {len(all_dates)}, 持仓周期: {hold_days} 天\n")

    for i, date in enumerate(all_dates):
        # 到期卖出
        to_sell = [s for s, sd in pending_sell.items() if sd <= date]
        for stock in to_sell:
            sell_stock(stock, date, reason="hold_end")
            del pending_sell[stock]

        # 每日净值
        day_value = get_value(date)
        daily_value.append({'date': date, 'value': day_value,
            'cash': cash, 'positions': len(positions)})

        # 选股（T-1 信号）
        if i == 0:
            continue
        prev_date = all_dates[i - 1]
        try:
            prev_scores = scores.xs(prev_date, level="datetime")
        except KeyError:
            continue
        prev_scores = prev_scores.dropna()
        if len(prev_scores) < top_k:
            continue

        selected = prev_scores.nlargest(top_k, 'score').index.tolist()

        # 调仓
        for stock in list(positions.keys()):
            if stock not in selected:
                sell_stock(stock, date, reason="rebalance")

        current_value = get_value(date)
        alloc_per_stock = current_value / top_k

        for stock in selected:
            if stock in positions:
                continue
            buy_stock(stock, date, alloc_per_stock)

        if (i + 1) % 100 == 0:
            print(f"  进度: {i+1}/{len(all_dates)} ({(i+1)/len(all_dates)*100:.1f}%)", end="\r")
    print(f"\n  进度: {len(all_dates)}/{len(all_dates)} (100.0%)")

    # 强制平仓
    last_date = all_dates[-1]
    for stock in list(positions.keys()):
        sell_stock(stock, last_date, reason="end")

    return daily_value, trade_log


# ═══════════════════════════════════════════════════════════
# 4. 指标计算与输出
# ═══════════════════════════════════════════════════════════

def compute_metrics(daily_value, trade_log):
    df = pd.DataFrame(daily_value).dropna(subset=['value']).set_index('date').sort_index()
    if len(df) < 2:
        return None
    nav = df['value'] / INITIAL_CAPITAL
    total_return = (nav.iloc[-1] - 1) * 100
    days = (nav.index[-1] - nav.index[0]).days
    years = days / 365.25
    ann_return = ((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0
    daily_ret = nav.pct_change().dropna()
    sharpe = (daily_ret.mean() * 252 - 0.02) / (daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0
    running_max = nav.cummax()
    drawdown = (nav - running_max) / running_max
    max_dd = drawdown.min() * 100
    sells = [t for t in trade_log if t['action'] == 'SELL']
    wins = [t for t in sells if t['pnl_pct'] > 0]
    win_rate = len(wins) / len(sells) * 100 if sells else 0
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = abs(np.mean([t['pnl_pct'] for t in sells if t['pnl_pct'] <= 0])) if sells and len([t for t in sells if t['pnl_pct'] <= 0]) > 0 else 1
    profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')
    return {
        'total_days': len(df), 'total_return_pct': round(total_return, 2),
        'annual_return_pct': round(ann_return, 2), 'sharpe_ratio': round(sharpe, 3),
        'max_drawdown_pct': round(max_dd, 2), 'win_rate_pct': round(win_rate, 1),
        'total_trades': len(sells), 'win_trades': len(wins),
        'profit_factor': round(profit_factor, 2), 'final_value': round(df['value'].iloc[-1], 2),
        'nav_curve': df[['value']].copy(),
    }


def main():
    print("=" * 70)
    print("  因子选股策略回测 v2 — 66 因子 Top 10（全量复权价格）")
    print("=" * 70)

    print("\n📂 步骤1: 计算复权价格...")
    adj_prices, split_stocks = compute_adjusted_prices()

    print("\n📂 步骤2: 加载因子得分...")
    scores = load_factor_scores(adj_prices)

    print(f"\n🚀 步骤3: 回测 (Top {TOP_K}, 持仓 {HOLD_DAYS} 天)...")
    daily_value, trade_log = run_backtest(adj_prices, scores, TOP_K, HOLD_DAYS)

    print("\n📊 回测结果")
    print("-" * 70)
    metrics = compute_metrics(daily_value, trade_log)
    print(f"  回测天数:           {metrics['total_days']}")
    print(f"  初始资金:           {INITIAL_CAPITAL:,.0f} 元")
    print(f"  最终净值:           {metrics['final_value']:,.0f} 元")
    print(f"  总收益率:           {metrics['total_return_pct']:+.2f}%")
    print(f"  年化收益率:         {metrics['annual_return_pct']:+.2f}%")
    print(f"  夏普比率:           {metrics['sharpe_ratio']:.3f}")
    print(f"  最大回撤:           {metrics['max_drawdown_pct']:.2f}%")
    print(f"  胜率:               {metrics['win_rate_pct']:.1f}%")
    print(f"  总交易次数:         {metrics['total_trades']}")
    print(f"  盈利交易:           {metrics['win_trades']}")
    print(f"  盈亏比:             {metrics['profit_factor']:.2f}")

    # 保存
    metrics['nav_curve'].to_csv("backtest_nav.csv")
    trades_df = pd.DataFrame(trade_log)
    trades_df.to_csv("backtest_trades.csv", index=False, encoding='utf-8-sig')
    print(f"\n💾 backtest_nav.csv / backtest_trades.csv")

    # 月度统计
    print("\n📅 月度收益统计:")
    print("-" * 70)
    df = pd.DataFrame(daily_value).dropna(subset=['value'])
    df = df.set_index('date').sort_index()
    monthly = df.groupby(df.index.to_period('M')).agg(
        start_val=('value', 'first'), end_val=('value', 'last'))
    monthly['ret'] = (monthly['end_val'] / monthly['start_val'] - 1) * 100
    monthly = monthly.sort_index()
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
    periods = [
        ("2022-09 ~ 2022-12", "2022-09-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
        ("2026-01~08", "2026-01-01", "2026-08-31"),
        ("2026-09", "2026-09-01", "2026-09-02"),
    ]
    for name, start, end in periods:
        sub = nav.loc[start:end]
        if len(sub) < 2:
            continue
        ret = (sub.iloc[-1] / sub.iloc[0] - 1) * 100
        print(f"  {name:15s}: {ret:+.2f}%")


if __name__ == "__main__":
    main()
