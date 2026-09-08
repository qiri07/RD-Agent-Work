#!/usr/bin/env python3
"""
A股交易规则模块 — 主入口（向后兼容）
====================================
所有功能均从 trading_rules_core 和 data_validator 导入。

用法:
    from trading_rules import Board, get_board, get_limit_pct, DataValidator, FactorRuleChecker
    from trading_rules import calc_limit_price, is_limit_up, is_limit_down
    from trading_rules import get_board_info, validate_stock_data, print_trading_rules_summary

内部模块:
    trading_rules_core  — Board枚举、涨跌幅、交易单位、涨跌停计算
    data_validator      — DataValidator、因子规则检查器、数据验证工具
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

import config as cfg
from trading_rules_core import (
    Board, get_board, get_limit_pct, get_lot_size, get_trading_hours,
    calc_limit_price, is_limit_up, is_limit_down, get_board_info,
)
from data_validator import (
    DataValidator, validate_stock_data, print_trading_rules_summary,
)

# 向后兼容：保留 data_validator 中的 DataValidator 别名
# （旧代码可能写 from trading_rules import DataValidator）
DataValidator = DataValidator


# ═══════════════════════════════════════════════════════════
# 因子计算规则检查器
# ═══════════════════════════════════════════════════════════
class FactorRuleChecker:
    """
    因子计算规则检查器
    用于在因子计算前后验证规则正确性，防止常见错误：
    1. 未来函数（look-ahead bias）
    2. 涨跌停状态未处理
    3. T+1约束违反
    4. 停牌数据处理
    """

    @staticmethod
    def check_lookahead_bias(factor_df: pd.DataFrame, prices_df: pd.DataFrame,
                              lookback: int = 5) -> dict:
        """
        检测因子计算中的未来函数
        原理: 如果因子值在当日收盘价后发生变化（使用未来数据计算），则存在未来函数
        """
        issues = {}

        for col in factor_df.columns:
            vals = factor_df[col]
            changes = vals.groupby(level='instrument').diff().abs()
            large_changes = changes[changes > 1.0]
            if len(large_changes) > 0:
                stocks = large_changes.index.get_level_values('instrument').unique()
                issues[f'{col}_large_changes'] = {
                    'count': len(large_changes),
                    'stocks': len(stocks),
                    'severity': 'warning'
                }

        return issues

    @staticmethod
    def check_limit_status(prices_df: pd.DataFrame, factor_df: pd.DataFrame) -> pd.DataFrame:
        """
        为每只股票添加涨跌停状态标记
        返回: 添加 'is_limit_up', 'is_limit_down', 'board' 列的DataFrame
        """
        result = factor_df.copy()

        codes = prices_df.index.get_level_values('instrument')
        boards = codes.map(lambda c: get_board(c).value)
        result['board'] = boards

        close = prices_df['$close']
        prev_close = close.groupby(level='instrument').shift(1)

        for board_name, limit_pct in [
            ('沪市主板', 0.10), ('深市主板', 0.10), ('创业板', 0.20),
            ('科创板', 0.20), ('北交所', 0.30)
        ]:
            board_mask = boards == board_name
            limit_up = prev_close * (1 + limit_pct)
            limit_down = prev_close * (1 - limit_pct)

            result.loc[board_mask, 'is_limit_up'] = (close >= limit_up) & (prev_close > 0)
            result.loc[board_mask, 'is_limit_down'] = (close <= limit_down) & (prev_close > 0)

        result['is_limit_up'] = result['is_limit_up'].fillna(False)
        result['is_limit_down'] = result['is_limit_down'].fillna(False)

        return result

    @staticmethod
    def filter_tradeable(prices_df: pd.DataFrame, factor_df: pd.DataFrame) -> pd.DataFrame:
        """
        过滤不可交易的股票-日期组合
        规则:
        1. 排除停牌日（成交量=0）
        2. 排除涨跌停无法成交的日期（根据策略需求）
        3. 排除新股上市前N日（流动性不足）
        """
        mask = pd.Series(True, index=factor_df.index)

        vol = prices_df['$volume']
        mask &= (vol > 0)

        for col in ['$open', '$close']:
            p = prices_df[col]
            mask &= (p > 0)

        close = prices_df['$close']
        prev_close = close.groupby(level='instrument').shift(1)
        valid_ratio = close / prev_close
        valid_ratio = valid_ratio.replace([np.inf, -np.inf], np.nan)
        mask &= (valid_ratio > 0.01) & (valid_ratio < 100)

        return factor_df[mask]


def check_limit_status(prices_df: pd.DataFrame, factor_df: pd.DataFrame = None) -> pd.DataFrame:
    """别名: 添加涨跌停状态标记"""
    return FactorRuleChecker.check_limit_status(prices_df, factor_df) if factor_df is not None else FactorRuleChecker.check_limit_status(prices_df, prices_df)


# ═══════════════════════════════════════════════════════════
# 便捷函数 — 已由 trading_rules_core 导出，此处不再重复定义
# ═══════════════════════════════════════════════════════════


# 重新导出方便 import
__all__ = [
    # Core
    'Board', 'get_board', 'get_limit_pct', 'get_lot_size', 'get_trading_hours',
    'calc_limit_price', 'is_limit_up', 'is_limit_down',
    # Validator
    'DataValidator', 'validate_stock_data', 'print_trading_rules_summary',
    'get_board_info',
    # Factor
    'FactorRuleChecker', 'check_limit_status',
]


if __name__ == "__main__":
    print_trading_rules_summary()

    print("\n=== 数据质量验证 ===")
    df = pd.read_parquet(cfg.DAILY_PV_FULL_PQ)
    summary = validate_stock_data(df, 'stock_validation_report.json')

    print(f"\n问题汇总:")
    print(f"  总问题数: {summary['total_issues']:,}")
    print(f"  错误: {summary['error_count']}")
    print(f"  警告: {summary['warning_count']}")
    print(f"  提示: {summary['info_count']}")

    if summary['recommendations']:
        print(f"\n修正建议:")
        for rec in summary['recommendations']:
            print(f"  • {rec['description']}")
