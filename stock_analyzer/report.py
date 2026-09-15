#!/usr/bin/env python3
"""
报告生成
========
负责生成 JSON 报告和 CSV 文件输出。
"""
import json
from datetime import datetime
from pathlib import Path
import pandas as pd


def generate_report(
    ticker: str,
    display_name: str,
    src_pq: Path,
    dates,
    n_days: int,
    close,
    stats: dict,
    yearly_stats: list,
    backtest_results: list,
    ic_records: list,
    factor_df,
    out_dir: Path,
) -> dict:
    """生成综合分析JSON报告"""
    report = {
        'target': display_name,
        'ticker': ticker,
        'data_source': str(src_pq),
        'data_range': {
            'start': str(dates.min().date()),
            'end': str(dates.max().date()),
            'trading_days': n_days,
        },
        'price_stats': {
            'min_close': float(close.min()),
            'max_close': float(close.max()),
            'mean_close': float(close.mean()),
        },
        'return_stats': {
            'annual_return_pct': round(stats['ann_ret'] * 100, 2),
            'annual_volatility_pct': round(stats['ann_vol'] * 100, 2),
            'sharpe_ratio': round(stats['sharpe'], 2),
            'max_drawdown_pct': round(stats['max_dd'] * 100, 2),
        },
        'yearly_performance': yearly_stats,
        'backtest_results': backtest_results,
        'factor_ic': ic_records,
        'factor_count': len(factor_df.columns),
        'factor_names': factor_df.columns.tolist(),
        'output_dir': str(out_dir.absolute()),
        'timestamp': datetime.now().isoformat(),
    }

    with open(out_dir / f'{ticker.lower()}_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    return report


def save_cross_sectional_ic(ticker: str, workspace, out_dir: Path) -> int:
    """保存横截面 IC 定位结果，返回匹配的因子数量"""
    import numpy as np
    ic_results = []
    for sid in sorted(workspace.iterdir()):
        if not sid.is_dir():
            continue
        h5 = sid / 'result.h5'
        if not h5.exists():
            continue
        try:
            fdf = pd.read_hdf(h5, key='data')
            fname = fdf.columns[0]
            fs = fdf[fname]
            if ticker in fs.index.get_level_values('instrument'):
                target_val = fs.xs(ticker, level='instrument', drop_level=False)
                ic_results.append({
                    'factor_id': sid.name,
                    'factor_name': fname,
                    'target_value': float(target_val.values[0]) if len(target_val) == 1 else np.nan,
                    'n_obs': len(fs.dropna()),
                })
        except Exception:
            continue

    if ic_results:
        ic_df = pd.DataFrame(ic_results)
        ic_df.to_csv(out_dir / f'{ticker.lower()}_ic.csv', index=False)
    return len(ic_results)


def save_ranking(ticker: str, dates, workspace, out_dir: Path):
    """保存横截面排名 CSV"""
    import numpy as np
    all_factor_data = {}
    for sid in sorted(workspace.iterdir()):
        if not sid.is_dir():
            continue
        h5 = sid / 'result.h5'
        if not h5.exists():
            continue
        try:
            fdf = pd.read_hdf(h5, key='data')
            all_factor_data[sid.name] = fdf.iloc[:, 0]
        except Exception:
            continue

    ranking_records = []
    for dt in sorted(dates.unique())[-30:]:
        row = {'date': dt.date()}
        for fid, fs in all_factor_data.items():
            try:
                val = fs.loc[(dt, ticker)]
                if np.isnan(val):
                    continue
                day_vals = fs.xs(dt, level=0, drop_level=False)
                if len(day_vals) < 50:
                    continue
                rank = day_vals.rank(pct=True).loc[ticker]
                row[fid[:12]] = f"{val:.4f} ({rank*100:.1f}%)"
            except (KeyError, TypeError):
                continue
        ranking_records.append(row)

    if ranking_records:
        rd = pd.DataFrame(ranking_records)
        rd.to_csv(out_dir / f'{ticker.lower()}_ranking.csv', index=False)
