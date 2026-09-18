#!/usr/bin/env python3
from __future__ import annotations
"""
白名单股票因子分析与回测
========================
对指定白名单股票进行因子计算、IC分析和回测

用法:
    python3 whitelist_backtest.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from engine.pricing import PriceEngine
from engine.backtest import BacktestEngine
from engine.metrics import PerformanceAnalyzer

WHITELIST = [
    'SH603558', 'SH601061', 'SH601899', 'SH600007', 'SH603993',
    'SH600210', 'SH601088', 'SZ002027', 'SH600900', 'SH600036',
    'SH603288', 'SH601166', 'SZ002893', 'SH601336', 'SH601318',
    'SZ000651', 'SH600887', 'SH601225', 'SZ000895', 'SH600600',
    'SH601006', 'SH600938', 'SH600132', 'SZ000001', 'SH600519',
    'SH601668', 'SH600660', 'SH605305', 'SH603486', 'SZ000333'
]

BACKTEST_TOP_K = 10
BACKTEST_HOLD_DAYS = 5
INITIAL_CAPITAL = 1_000_000


def load_whitelist_data():
    df = pd.read_parquet(cfg.DAILY_PV_FULL_PQ)
    mask = df.index.get_level_values('instrument').isin(WHITELIST)
    df = df[mask].copy()
    df.index = df.index.set_names(['datetime', 'instrument'])
    df = df.sort_index()
    df = df[~df.index.duplicated(keep='first')]
    print(f"📊 白名单数据: {len(df):,} 行, {df.index.get_level_values('instrument').nunique()} 只股票")
    print(f"   日期范围: {df.index.get_level_values('datetime').min().date()} ~ "
          f"{df.index.get_level_values('datetime').max().date()}")
    return df


def compute_factors(df):
    """计算因子"""
    print("\n🧮 计算因子...")
    
    all_insts = df.index.get_level_values('instrument').unique()
    
    factor_names = [
        'momentum_5d', 'momentum_10d', 'momentum_20d',
        'reversal_5d', 'volatility_20d', 'rsi_14', 'macd', 'bollinger_pos', 'volume_ratio'
    ]
    
    all_rows = []
    
    for inst in all_insts:
        stock = df.xs(inst, level='instrument')
        close = stock['$close'].values
        volume = stock['$volume'].values
        dates = stock.index
        
        # 动量因子
        for period in [5, 10, 20]:
            name = f'momentum_{period}d'
            result = np.full(len(close), np.nan)
            for i in range(period, len(close) - period):
                result[i] = close[i] / close[i - period] - 1
            result = np.roll(result, -period)
            result[-period:] = np.nan
            for d, r in zip(dates, result):
                all_rows.append((d, inst, name, r))
        
        # 反转因子
        name = 'reversal_5d'
        result = np.full(len(close), np.nan)
        for i in range(5, len(close) - 5):
            result[i] = -(close[i] / close[i - 5] - 1)
        result = np.roll(result, -5)
        result[-5:] = np.nan
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))
        
        # 波动率因子
        name = 'volatility_20d'
        rets = np.diff(np.log(close))
        result = np.full(len(close), np.nan)
        for i in range(20, len(close)):
            result[i] = np.std(rets[i-20:i], ddof=1) * np.sqrt(252)
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))
        
        # RSI因子
        name = 'rsi_14'
        delta = np.diff(close)
        gain = np.maximum(delta, 0)
        loss = np.maximum(-delta, 0)
        result = np.full(len(close), np.nan)
        for i in range(14, len(close)):
            avg_g = np.mean(gain[i-14:i])
            avg_l = np.mean(loss[i-14:i])
            if avg_l == 0:
                result[i] = 100
            else:
                rs = avg_g / avg_l
                result[i] = 100 - 100 / (1 + rs)
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))
        
        # MACD因子
        name = 'macd'
        result = np.full(len(close), np.nan)
        ema12 = close[0]
        ema26 = close[0]
        k12 = 2/13
        k26 = 2/27
        for i in range(1, len(close)):
            ema12 = close[i] * k12 + ema12 * (1 - k12)
            ema26 = close[i] * k26 + ema26 * (1 - k26)
            result[i] = ema12 - ema26
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))
        
        # 布林带因子
        name = 'bollinger_pos'
        result = np.full(len(close), np.nan)
        for i in range(20, len(close)):
            ma = np.mean(close[i-20:i])
            sd = np.std(close[i-20:i], ddof=1)
            if sd > 0:
                result[i] = (close[i] - ma) / (2 * sd)
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))
        
        # 换手率因子
        name = 'volume_ratio'
        result = np.full(len(close), np.nan)
        for i in range(20, len(close)):
            ma = np.mean(volume[i-20:i])
            if ma > 0:
                result[i] = volume[i] / ma
        for d, r in zip(dates, result):
            all_rows.append((d, inst, name, r))
    
    result_df = pd.DataFrame(all_rows, columns=['datetime', 'instrument', 'factor', 'value'])
    factors_df = result_df.pivot(index=['datetime', 'instrument'], columns='factor', values='value')
    factors_df.index.names = ['datetime', 'instrument']
    factors_df = factors_df.sort_index()
    
    for name in factor_names:
        if name in factors_df.columns:
            valid = factors_df[name].dropna().shape[0]
            print(f"  ✅ {name}: {valid:,} 有效值")
    
    return factors_df


def compute_ic(factors_df, df):
    """计算IC"""
    print("\n📊 计算 IC...")
    
    # 计算 forward returns
    returns_data = []
    for inst in df.index.get_level_values('instrument').unique():
        stock = df.xs(inst, level='instrument')
        close = stock['$close'].values
        fwd_ret = np.full(len(close), np.nan)
        for i in range(5, len(close) - 5):
            fwd_ret[i] = close[i+5] / close[i] - 1
        for d, r in zip(stock.index, fwd_ret):
            returns_data.append((d, inst, r))
    
    returns_df = pd.DataFrame(returns_data, columns=['datetime', 'instrument', 'return'])
    returns_df.set_index(['datetime', 'instrument'], inplace=True)
    
    ic_results = []
    
    for fid in factors_df.columns:
        merged = pd.DataFrame({
            'factor': factors_df[fid].values,
            'return': returns_df['return'].values
        }, index=factors_df.index)
        merged = merged.dropna()
        
        if len(merged) < 50:
            continue
        
        daily_ics = []
        for date, group in merged.groupby(level='datetime'):
            if len(group) < 3:
                continue
            f_vals = group['factor'].values
            r_vals = group['return'].values
            ic, _ = rankdata(f_vals), rankdata(r_vals)
            ic_val = np.corrcoef(ic, r_vals)[0, 1]
            if np.isfinite(ic_val):
                daily_ics.append(ic_val)
        
        if len(daily_ics) < 5:
            continue
        
        ic_mean = np.mean(daily_ics)
        ic_std = np.std(daily_ics)
        ic_t = ic_mean / (ic_std / np.sqrt(len(daily_ics))) if ic_std > 0 else 0
        ic_pos = sum(1 for x in daily_ics if x > 0) / len(daily_ics)
        
        ic_results.append({
            'factor_id': fid,
            'IC_5d': ic_mean,
            'IC_t_5d': ic_t,
            'IC_pos_5d': ic_pos,
            'n_days': len(daily_ics)
        })
        
        print(f"  {fid}: IC={ic_mean:+.4f}, t={ic_t:.2f}, pos={ic_pos:.1%}")
    
    ic_df = pd.DataFrame(ic_results).sort_values('IC_5d', key=abs, ascending=False)
    return ic_df


def synthesize_score(day_factors):
    """合成因子得分（横截面 Z-score + 等权）"""
    if not day_factors:
        return None
    
    # 构建 DataFrame
    df = pd.DataFrame(day_factors)
    
    # 横截面 Z-score 标准化
    for col in df.columns:
        mean = df[col].mean()
        std = df[col].std()
        df[col] = ((df[col] - mean) / std).fillna(0) if std > 0 else 0
    
    # 等权合成
    n_factors = len(df.columns)
    df['composite_score'] = df.sum(axis=1) / n_factors
    df['rank'] = df['composite_score'].rank(ascending=False, method='dense').astype(int)
    df = df.sort_values('composite_score', ascending=False)
    
    return df


def run_backtest(df, factors_df, ic_df, top_k=10, hold_days=5):
    """运行回测"""
    print("\n🚀 运行回测...")
    
    # 选择 Top N 因子（排除异常高IC）
    valid_factors = ic_df[ic_df['IC_5d'].abs() < 0.5]['factor_id'].tolist()
    if len(valid_factors) >= 3:
        top_factors = valid_factors[:5]
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
            
        except Exception as e:
            continue
    
    print(f"  生成信号: {len(signals)} 个交易日")
    
    # 加载价格
    price_engine = PriceEngine()
    price_map = price_engine.build_price_map(df)
    
    # 运行回测
    bt_engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
    result = bt_engine.run(all_dates, price_map, signals, hold_days, top_k)
    
    # 绩效分析
    analyzer = PerformanceAnalyzer(initial_capital=INITIAL_CAPITAL)
    metrics = analyzer.analyze(result.daily_value, result.trades)
    
    print(f"\n{'='*60}")
    print(f"  回测结果")
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
    
    print("=" * 70)
    print("  白名单股票因子分析与回测")
    print("=" * 70)
    print(f"\n白名单: {len(WHITELIST)} 只股票")
    
    df = load_whitelist_data()
    factors_df = compute_factors(df)
    ic_df = compute_ic(factors_df, df)
    
    ic_df.to_csv('whitelist_ic_results.csv', index=False)
    print(f"\n💾 IC 结果已保存: whitelist_ic_results.csv")
    
    metrics, result = run_backtest(df, factors_df, ic_df, 
                                    top_k=BACKTEST_TOP_K, 
                                    hold_days=BACKTEST_HOLD_DAYS)
    
    nav_df = pd.DataFrame(result.daily_value)
    nav_df.to_csv('whitelist_backtest_nav.csv', index=False)
    
    trades_df = pd.DataFrame(result.trades)
    trades_df.to_csv('whitelist_backtest_trades.csv', index=False)
    
    print(f"\n💾 回测结果已保存:")
    print(f"  - whitelist_backtest_nav.csv")
    print(f"  - whitelist_backtest_trades.csv")
    
    print(f"\n总耗时: {time.time() - t_start:.1f}s")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
