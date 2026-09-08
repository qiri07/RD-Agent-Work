#!/usr/bin/env python3
"""
因子计算规则矫正器
==================
在因子计算过程中自动应用交易规则，防止常见错误。

主要功能:
1. 涨跌停状态标记 — 标记每只股票每日是否涨停/跌停
2. 停牌过滤 — 剔除成交量为0的日期
3. 异常价格修正 — 修正超出合理范围的价格
4. 未来函数检测 — 检测因子计算中的前瞻性偏差
5. 板块适配 — 不同板块使用不同的涨跌幅限制
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

import config as cfg
from trading_rules import (
    get_board, get_limit_pct, get_lot_size,
    calc_limit_price, is_limit_up, is_limit_down,
    DataValidator, FactorRuleChecker,
)


def add_limit_status(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    为价格数据添加涨跌停状态标记
    返回: 添加 is_limit_up, is_limit_down, board, limit_up_price, limit_down_price 列
    """
    result = prices_df.copy()
    close = result['$close']
    prev_close = close.groupby(level='instrument', sort=False).shift(1)

    # 获取每只股票的板块
    codes = result.index.get_level_values('instrument')
    boards = codes.map(lambda c: get_board(c))
    result['board'] = boards

    # 计算每只股票的涨跌停限制
    limits = boards.map(lambda b: get_limit_pct(b))
    limit_up_price = prev_close * (1 + limits)
    limit_down_price = prev_close * (1 - limits)

    # 标记涨跌停状态
    result['is_limit_up'] = (close >= limit_up_price) & (prev_close > 0)
    result['is_limit_down'] = (close <= limit_down_price) & (prev_close > 0)

    # 标记涨停价/跌停价
    result['limit_up_price'] = limit_up_price
    result['limit_down_price'] = limit_down_price

    # 填充首日的NaN
    result['is_limit_up'] = result['is_limit_up'].fillna(False)
    result['is_limit_down'] = result['is_limit_down'].fillna(False)

    return result


def correct_price_anomalies(prices_df: pd.DataFrame, clip_pct: float = 0.99) -> pd.DataFrame:
    """
    修正价格异常
    规则:
    1. 价格为负 → 置为NaN
    2. 价格>10000 → 截断到10000
    3. 成交量异常放大 → winsorize到99%分位
    """
    corrected = prices_df.copy()

    # 修正负价格
    for col in ['$open', '$close', '$high', '$low']:
        mask = corrected[col] <= 0
        corrected.loc[mask, col] = np.nan

    # 截断异常高价
    for col in ['$open', '$close', '$high', '$low']:
        mask = corrected[col] > 10000
        corrected.loc[mask, col] = 10000.0

    # Winsorize 成交量（转为 float 避免 int64 赋值报错）
    corrected['$volume'] = corrected['$volume'].astype(float)
    vol_pct = corrected['$volume'].groupby(level='instrument').transform(lambda x: x.quantile(clip_pct))
    mask = corrected['$volume'] > vol_pct
    corrected.loc[mask, '$volume'] = vol_pct[mask].values

    return corrected


def filter_tradeable_dates(prices_df: pd.DataFrame, min_volume: float = 100) -> pd.DataFrame:
    """
    过滤不可交易的日期
    规则:
    1. 成交量 < min_volume → 停牌
    2. 开盘价或收盘价为 NaN → 跳过
    """
    mask = (prices_df['$volume'] >= min_volume) & \
           (prices_df['$open'].notna()) & \
           (prices_df['$close'].notna())
    return prices_df[mask]


def detect_lookahead_bias(factor_df: pd.DataFrame, prices_df: pd.DataFrame,
                           max_change: float = 1.0) -> dict:
    """
    检测因子计算中的未来函数
    方法: 检查因子值在相邻日期的异常大幅变化
    """
    issues = {}
    for col in factor_df.columns:
        vals = factor_df[col]
        changes = vals.groupby(level='instrument').diff().abs()
        large = changes[changes > max_change]
        if len(large) > 0:
            issues[col] = {
                'large_changes': len(large),
                'stocks': len(large.index.get_level_values('instrument').unique()),
                'severity': 'warning' if len(large) < 100 else 'error'
            }
    return issues


def validate_factor_calculation(factor_df: pd.DataFrame, prices_df: pd.DataFrame,
                                 factor_name: str = "unknown") -> dict:
    """
    验证单个因子的计算结果
    返回验证报告
    """
    report = {
        'factor_name': factor_name,
        'shape': factor_df.shape,
        'date_range': (
            str(factor_df.index.get_level_values(0).min().date()),
            str(factor_df.index.get_level_values(0).max().date())
        ),
        'stocks': factor_df.index.get_level_values(1).nunique(),
        'missing_pct': factor_df.isna().mean().mean() * 100,
        'issues': {},
    }

    # 1. 检查因子值范围
    for col in factor_df.columns:
        vals = factor_df[col].dropna()
        if len(vals) > 0:
            report['issues'][f'{col}_range'] = {
                'min': float(vals.min()),
                'max': float(vals.max()),
                'mean': float(vals.mean()),
                'std': float(vals.std()),
            }

    # 2. 检测未来函数
    lookahead = detect_lookahead_bias(factor_df, prices_df)
    if lookahead:
        report['issues']['lookahead_bias'] = lookahead

    # 3. 检查与价格数据的一致性
    common_idx = factor_df.index.intersection(prices_df.index)
    if len(common_idx) > 0:
        # 检查涨跌停日的因子分布
        prices_with_limit = add_limit_status(prices_df.loc[common_idx])
        limit_up_mask = prices_with_limit['is_limit_up']
        limit_down_mask = prices_with_limit['is_limit_down']

        for col in factor_df.columns:
            if limit_up_mask.any():
                up_mean = factor_df.loc[limit_up_mask, col].mean()
                down_mean = factor_df.loc[limit_down_mask, col].mean()
                report['issues'][f'{col}_limit_up_mean'] = float(up_mean) if not np.isnan(up_mean) else None
                report['issues'][f'{col}_limit_down_mean'] = float(down_mean) if not np.isnan(down_mean) else None

    return report


def run_full_validation(output_path: str = None) -> dict:
    """
    运行完整的数据质量和因子规则验证
    """
    print("=" * 60)
    print("  因子计算规则矫正验证")
    print("=" * 60)

    # 加载价格数据
    print("\n📂 加载价格数据...")
    prices = pd.read_parquet(cfg.DAILY_PV_FULL_PQ)
    prices = prices.sort_index()
    print(f"  原始数据: {len(prices):,} 行, {prices.index.get_level_values('instrument').nunique():,} 只")

    # 1. 价格异常修正
    print("\n🔧 步骤1: 价格异常修正...")
    prices_corrected = correct_price_anomalies(prices)
    print(f"  修正后: {prices_corrected['$close'].isna().sum():,} 个NaN价格")

    # 2. 过滤不可交易日
    print("\n🔧 步骤2: 过滤不可交易日...")
    prices_tradeable = filter_tradeable_dates(prices_corrected)
    print(f"  可交易日: {prices_tradeable.index.get_level_values(0).nunique():,} 天")

    # 3. 添加涨跌停状态
    print("\n🔧 步骤3: 添加涨跌停状态标记...")
    prices_limited = add_limit_status(prices_tradeable)
    limit_up_count = prices_limited['is_limit_up'].sum()
    limit_down_count = prices_limited['is_limit_down'].sum()
    print(f"  涨停日: {limit_up_count:,}, 跌停日: {limit_down_count:,}")

    # 4. 数据质量验证
    print("\n🔍 步骤4: 数据质量验证...")
    validator = DataValidator(prices_tradeable)
    issues = validator.validate_all()
    print(f"  发现问题: {len(issues)} 类")
    for name, info in issues.items():
        print(f"    • {info['detail']}")

    # 5. 验证因子计算结果
    print("\n🔍 步骤5: 因子计算结果验证...")
    ws = cfg.RDAGENT_WORKSPACE
    factor_reports = []
    for d in sorted(ws.iterdir()):
        if not d.is_dir():
            continue
        h5 = d / "result.h5"
        if not h5.exists():
            continue
        try:
            df = pd.read_hdf(h5, key="data")
            col = df.columns[0]
            # 对齐索引
            df.index.names = ['datetime', 'instrument']
            report = validate_factor_calculation(df, prices_tradeable, factor_name=d.name)
            factor_reports.append(report)

            # 检查重大问题
            if report['issues'].get('lookahead_bias'):
                lb = report['issues']['lookahead_bias']
                total_issues = sum(v['large_changes'] for v in lb.values())
                if total_issues > 100:
                    print(f"  ⚠️  {d.name}: 未来函数嫌疑 ({total_issues}条异常变化)")
        except Exception as e:
            print(f"  ❌ {d.name}: {e}")

    # 6. 汇总报告
    print(f"\n{'='*60}")
    print("  验证汇总")
    print(f"{'='*60}")
    total_factors = len(factor_reports)
    factors_with_issues = sum(1 for r in factor_reports if r['issues'])
    print(f"  验证因子数: {total_factors}")
    print(f"  有问题因子: {factors_with_issues}")
    print(f"  数据覆盖: {prices_tradeable.index.get_level_values(0).min().date()} ~ "
          f"{prices_tradeable.index.get_level_values(0).max().date()}")

    # 保存报告
    if output_path:
        import json
        with open(output_path, 'w') as f:
            json.dump({
                'prices_shape': list(prices_tradeable.shape),
                'dates_range': [str(prices_tradeable.index.get_level_values(0).min().date()),
                               str(prices_tradeable.index.get_level_values(0).max().date())],
                'issues': issues,
                'factor_reports': factor_reports,
            }, f, indent=2, ensure_ascii=False, default=str)
        print(f"  💾 报告已保存: {output_path}")

    return {
        'prices_shape': prices_tradeable.shape,
        'issues': issues,
        'factor_reports': factor_reports,
    }


if __name__ == "__main__":
    run_full_validation('factor_validation_report.json')
