#!/usr/bin/env python3
"""
A股数据矫正器
==============
用于检测和修复数据质量问题，主要包括：
1. 拆分/除权事件检测与历史价格修正
2. 异常高价数据修正（错误调整因子导致）
3. 涨跌停违规修正（超出板块限制的价格裁剪）
4. 成交量异常修正

使用方法:
    python3 data_corrector.py [--apply] [--output parquet|h5]
    
    --apply       应用修正并保存
    --output      输出格式: parquet (默认) 或 h5
    --dry-run     仅报告问题，不保存
"""

from __future__ import annotations

import argparse
import sys
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional

import config as cfg
from trading_rules import get_board, get_limit_pct, Board


# ═══════════════════════════════════════════════════════════
# 拆分事件检测
# ═══════════════════════════════════════════════════════════
def detect_split_events(df: pd.DataFrame, ratio_threshold: float = 0.3) -> list[dict]:
    """
    检测股票拆分/除权事件
    返回: [{date, code, prev_close, curr_close, ratio, adjustment_factor}, ...]
    adjustment_factor = prev_close / curr_close （需要将历史价格乘以这个值来修正）
    """
    close = df['$close']
    prev_close = close.groupby(level='instrument').shift(1)
    price_ratio = close / prev_close
    price_ratio = price_ratio.replace([np.inf, -np.inf], np.nan)

    events = []
    for (date, code), ratio in price_ratio.items():
        if pd.isna(ratio) or ratio <= 0:
            continue
        if ratio < ratio_threshold:
            date_val = date[0] if isinstance(date, tuple) else date
            # 直接用 ratio 反推 prev（避免 MultiIndex 重复键的 loc 问题）
            curr_raw = close.loc[(date, code)]
            curr = float(curr_raw.iloc[0] if hasattr(curr_raw, 'iloc') else curr_raw)
            if curr <= 0:
                continue
            prev = curr * ratio
            if prev > 0:
                adj_factor = prev / curr
                events.append({
                    'date': str(date_val.date() if hasattr(date_val, 'date') else date_val),
                    'code': code,
                    'prev_close': float(prev),
                    'curr_close': float(curr),
                    'ratio': float(ratio),
                    'adjustment_factor': float(adj_factor),
                })
    return events


def is_batch_split_event(events: list[dict]) -> bool:
    """
    判断是否为批量拆分事件（同一日期大量股票同时拆分）
    真实拆分不会在同一日影响超过10只股票
    """
    date_counts: dict[str, int] = {}
    for e in events:
        d = e['date']
        date_counts[d] = date_counts.get(d, 0) + 1
    return any(cnt > 10 for cnt in date_counts.values())


def classify_data_issues(df: pd.DataFrame) -> dict:
    """
    全面分类数据问题
    """
    close = df['$close']
    issues = {
        'split_events': [],
        'batch_anomalies': [],
        'extreme_prices': [],
        'invalid_records': [],
    }

    # 1. 检测拆分事件
    splits = detect_split_events(df)
    issues['split_events'] = splits
    print(f"  检测到 {len(splits)} 个拆分事件")

    # 2. 检查是否批量异常
    if is_batch_split_event(splits):
        date_counts: dict[str, list] = {}
        for e in splits:
            d = e['date']
            if d not in date_counts:
                date_counts[d] = []
            date_counts[d].append(e['code'])
        for d, codes in date_counts.items():
            if len(codes) > 10:
                issues['batch_anomalies'].append({
                    'date': d,
                    'count': len(codes),
                    'stocks': codes[:10],
                })
                print(f"  ⚠️  批量异常日期 {d}: {len(codes)} 只股票")

    # 3. 极端高价检测
    high_price_mask = close > 500
    if high_price_mask.any():
        high_codes = df[high_price_mask].index.get_level_values('instrument').unique().tolist()
        issues['extreme_prices'] = [
            {'code': c, 'max_price': float(close[close.index.get_level_values('instrument')==c].max())}
            for c in high_codes
        ]
        print(f"  ⚠️  {len(high_codes)} 只股票存在极端高价 (>500)")

    # 4. 零成交量异常（复牌日）
    zero_vol = df[df['$volume'] == 0]
    if len(zero_vol) > 0:
        zero_codes = zero_vol.index.get_level_values('instrument').unique().tolist()
        issues['invalid_records'] = [
            {'code': c, 'zero_vol_count': int((zero_vol.index.get_level_values('instrument')==c).sum())}
            for c in zero_codes[:20]
        ]
        print(f"  发现 {len(zero_vol)} 条零成交量记录（复牌日）")

    return issues


# ═══════════════════════════════════════════════════════════
# 数据修正
# ═══════════════════════════════════════════════════════════
def correct_batch_anomalies(df: pd.DataFrame, events: list[dict]) -> pd.DataFrame:
    """
    修正批量异常事件导致的错误历史数据
    """
    corrected = df.copy()
    close_col = '$close'

    batch_dates = set()
    for e in events:
        if e['ratio'] < 0.01:
            batch_dates.add(e['date'])

    if not batch_dates:
        return corrected

    print(f"  修正 {len(batch_dates)} 个批量异常日期...")

    for date_str in sorted(batch_dates):
        mask = corrected.index.get_level_values(0) == pd.Timestamp(date_str)
        if not mask.any():
            continue
        sub = corrected.loc[mask]
        extreme = sub[close_col] > 1000
        if extreme.any():
            print(f"    {date_str}: 修正 {extreme.sum()} 条异常记录")
            idx = sub.index[extreme.values]
            corrected.loc[idx, close_col] = np.nan
            for col in ['$open', '$high', '$low']:
                if col in corrected.columns:
                    corrected.loc[idx, col] = np.nan

    return corrected


def correct_single_stock_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    修正单只股票的特定异常（整段历史价格错误）
    """
    corrected = df.copy()
    close_col = '$close'

    for code in df.index.get_level_values('instrument').unique():
        mask = corrected.index.get_level_values('instrument') == code
        sub = corrected.loc[mask].sort_index()
        if len(sub) < 10:
            continue

        close = sub[close_col]
        median_price = close.median()
        if median_price > 500:
            prev_close = close.shift(1)
            ratio = close / prev_close
            ratio = ratio.replace([np.inf, -np.inf], np.nan)
            abnormal_mask = ratio < 0.5
            first_abnormal = abnormal_mask.idxmax() if abnormal_mask.any() else None

            if first_abnormal is not None and median_price > 5000:
                after_abnormal = corrected.loc[mask].index >= first_abnormal
                if after_abnormal.any():
                    n_corrected = after_abnormal.sum()
                    print(f"    {code}: 修正 {n_corrected} 条异常记录 (median={median_price:.1f})")
                    # first_abnormal 可能是 tuple (date, code) 或 scalar date
                    abs_date = first_abnormal[0] if isinstance(first_abnormal, tuple) else first_abnormal
                    idx = corrected.index.get_level_values('instrument') == code
                    idx = idx & (corrected.index.get_level_values(0) >= abs_date)
                    corrected.loc[idx, close_col] = np.nan
                    for col in ['$open', '$high', '$low']:
                        if col in corrected.columns:
                            corrected.loc[idx, col] = np.nan

    return corrected


def apply_trading_rule_corrections(df: pd.DataFrame) -> pd.DataFrame:
    """
    应用交易规则层面的数据修正
    """
    corrected = df.copy()
    close_col = '$close'

    # 负价格修正
    for col in ['$open', '$close', '$high', '$low']:
        if col in corrected.columns:
            mask = corrected[col] <= 0
            corrected.loc[mask, col] = np.nan

    # 涨跌幅违规修正
    close = corrected[close_col]
    prev_close = close.groupby(level='instrument').shift(1)
    codes = corrected.index.get_level_values('instrument')
    boards = codes.map(lambda c: get_board(c))
    limits = boards.map(lambda b: get_limit_pct(b))
    limit_up = prev_close * (1 + limits)
    limit_down = prev_close * (1 - limits)

    for col in ['$open', '$high', '$low', '$close']:
        if col not in corrected.columns:
            continue
        mask_up = corrected[col] > limit_up
        mask_down = corrected[col] < limit_down
        corrected.loc[mask_up & (limit_up > 0), col] = limit_up[mask_up & (limit_up > 0)]
        corrected.loc[mask_down & (limit_down > 0), col] = limit_down[mask_down & (limit_down > 0)]

    # 成交量 winsorize（先转为 float 避免 int64 赋值报错）
    corrected['$volume'] = corrected['$volume'].astype(float)
    vol_upper = corrected['$volume'].groupby(level='instrument').transform(lambda x: x.quantile(0.995))
    mask = corrected['$volume'] > vol_upper
    corrected.loc[mask, '$volume'] = vol_upper[mask].values

    return corrected


def correct_data(df: pd.DataFrame, apply_all: bool = True) -> tuple[pd.DataFrame, dict]:
    """
    全面数据矫正
    """
    report = {
        'original_shape': list(df.shape),
        'corrections': {},
    }

    print("  步骤1: 分析数据问题...")
    issues = classify_data_issues(df)
    report['issues'] = {
        'split_events_count': len(issues['split_events']),
        'batch_anomalies': issues['batch_anomalies'],
        'extreme_price_stocks': len(issues['extreme_prices']),
    }

    corrected = df.copy()
    if apply_all and issues['batch_anomalies']:
        print("  步骤2: 修正批量异常...")
        corrected = correct_batch_anomalies(corrected, issues['split_events'])

    if apply_all:
        print("  步骤3: 修正单只股票异常...")
        corrected = correct_single_stock_anomalies(corrected)

    print("  步骤4: 应用交易规则修正...")
    corrected = apply_trading_rule_corrections(corrected)

    report['corrections']['final_shape'] = list(corrected.shape)
    report['corrections']['nan_close_count'] = int(corrected['$close'].isna().sum())
    report['corrections']['total_rows_removed'] = report['corrections']['nan_close_count']

    return corrected, report


def main():
    parser = argparse.ArgumentParser(description='A股数据矫正器')
    parser.add_argument('--apply', action='store_true', help='应用修正并保存')
    parser.add_argument('--output', choices=['parquet', 'h5'], default='parquet')
    parser.add_argument('--dry-run', action='store_true', help='仅报告问题，不保存')
    args = parser.parse_args()

    print("=" * 60)
    print("  A股数据矫正器")
    print("=" * 60)

    print("\n📂 加载数据...")
    df = pd.read_parquet(cfg.DAILY_PV_FULL_PQ)
    print(f"  原始数据: {len(df):,} 行, {df.index.get_level_values('instrument').nunique():,} 只")

    print("\n🔧 运行数据矫正...")
    corrected, report = correct_data(df, apply_all=not args.dry_run)

    print(f"\n{'='*60}")
    print("  矫正报告")
    print(f"{'='*60}")
    print(f"  原始数据: {report['corrections'].get('original_shape', 'N/A')}")
    print(f"  修正后:   {report['corrections'].get('final_shape', 'N/A')}")
    print(f"  修正行数: {report['corrections'].get('total_rows_removed', 0):,}")
    print(f"  NaN close: {report['corrections'].get('nan_close_count', 0):,}")

    if args.dry_run:
        print("\n  (仅报告模式，未保存)")
        return

    out_dir = cfg.FACTOR_SOURCE
    if args.output == 'parquet':
        out_path = out_dir / "daily_pv_full_corrected.parquet"
        corrected.to_parquet(out_path)
        print(f"\n  💾 已保存: {out_path}")
    else:
        out_path = out_dir / "daily_pv_full_corrected.h5"
        corrected.to_hdf(out_path, key='data', mode='w')
        print(f"\n  💾 已保存: {out_path}")

    report_path = cfg.PROJECT_ROOT / "data_correction_report.json"
    import json
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"  💾 报告已保存: {report_path}")


if __name__ == "__main__":
    main()
