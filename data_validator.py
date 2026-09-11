#!/usr/bin/env python3
"""
数据质量验证器
==============
A股数据质量验证，用于因子计算中的异常检测和数据修正。

功能:
  1. 价格异常检测（>10000 极端价格）
  2. 涨跌幅违规检测（超出板块限制）
  3. 成交量异常检测（均值+3σ）
  4. 开盘跳空检测（停牌复牌嫌疑）
  5. ST 股嫌疑检测
  6. 拆分/分红事件检测
  7. 自动修正建议生成与应用
"""

import numpy as np
import pandas as pd
from typing import Optional

import config as cfg
from trading_rules_core import Board, get_board, get_limit_pct, get_board_info


class DataValidator:
    """
    A股数据质量验证器
    用于检测因子计算中的常见错误：
    1. 价格异常（超出合理范围）
    2. 涨跌幅异常（超出涨跌停限制）
    3. 复权问题（拆分未处理）
    4. 停牌/复牌跳空
    5. ST状态识别
    """

    def __init__(self, prices_df: pd.DataFrame, max_retries: int = 3):
        """
        参数:
            prices_df: 价格DataFrame，MultiIndex (datetime, instrument), 列: $open/$close/$high/$low/$volume
            max_retries: 复权重试次数
        """
        self.prices = prices_df.copy()
        self.max_retries = max_retries
        self.issues = {}
        self.corrections = {}

    def validate_all(self) -> dict:
        """运行所有验证，返回问题汇总"""
        self.issues = {}
        self.corrections = {}

        self._check_price_range()
        self._check_return_limits()
        self._check_volume_anomalies()
        self._check_gap_anomalies()
        self._check_st_status()
        self._check_split_events()

        return self.issues

    def _check_price_range(self):
        """检查价格合理性"""
        issues = []
        for col in ['$open', '$close', '$high', '$low']:
            extreme = self.prices[col].abs() > 10000
            if extreme.any():
                count = extreme.sum()
                stocks = self.prices.loc[extreme].index.get_level_values('instrument').unique()
                issues.append({
                    'type': f'{col}_extreme',
                    'count': int(count),
                    'stocks': len(stocks),
                    'severity': 'warning' if count < 1000 else 'error',
                    'detail': f'{col} > 10000: {count}条, 涉及{len(stocks)}只股票'
                })
                key = f'{col}_extreme'
                self.issues[key] = issues[-1]

        return issues

    def _check_return_limits(self):
        """检查涨跌幅是否超出板块限制"""
        close = self.prices['$close']
        daily_ret = close.groupby(level='instrument').pct_change() * 100
        daily_ret = daily_ret.replace([np.inf, -np.inf], np.nan)

        violations = []
        for board, limit_pct in [
            (Board.SH_MAIN, 10), (Board.SZ_MAIN, 10), (Board.SZ_GEM, 20),
            (Board.SH_STAR, 20), (Board.BJ, 30)
        ]:
            board_codes = self.prices.index.get_level_values('instrument')
            board_mask = pd.Index(board_codes).map(lambda x: get_board(x) == board).values
            board_returns = daily_ret[board_mask]

            over_limit = board_returns.abs() > limit_pct + 0.5
            if over_limit.any():
                count = over_limit.sum()
                stocks = over_limit.index.get_level_values('instrument').unique()
                violations.append({
                    'type': f'{board.value}_return_violation',
                    'limit_pct': limit_pct,
                    'count': int(count),
                    'stocks': len(stocks),
                    'severity': 'error',
                    'detail': f'{board.value} 涨跌幅超{limit_pct}%: {count}条, {len(stocks)}只股票'
                })
                key = f'{board.value.lower().replace("市","")}_return_violation'
                self.issues[key] = violations[-1]

        return violations

    def _check_volume_anomalies(self):
        """检查成交量异常"""
        vol = self.prices['$volume']
        vol_mean = vol.groupby(level='instrument').transform('mean')
        vol_std = vol.groupby(level='instrument').transform('std')
        anomaly = vol > (vol_mean + 3 * vol_std.replace(0, np.nan))
        anomaly = anomaly & (vol > 0)

        if anomaly.any():
            count = anomaly.sum()
            stocks = self.prices[anomaly].index.get_level_values('instrument').unique()
            self.issues['volume_anomaly'] = {
                'type': 'volume_anomaly',
                'count': int(count),
                'stocks': len(stocks),
                'severity': 'warning',
                'detail': f'成交量异常放大: {count}条, {len(stocks)}只股票'
            }

    def _check_gap_anomalies(self):
        """检查开盘跳空异常（停牌复牌嫌疑）"""
        close = self.prices['$close']
        prev_close = close.groupby(level='instrument').shift(1)
        open_gap = (self.prices['$open'] / prev_close - 1) * 100
        open_gap = open_gap.replace([np.inf, -np.inf], np.nan)

        large_gap = open_gap.abs() > 10
        if large_gap.any():
            count = large_gap.sum()
            self.issues['open_gap'] = {
                'type': 'open_gap',
                'count': int(count),
                'severity': 'info',
                'detail': f'开盘跳空>10%: {count}条（可能含停牌复牌）'
            }

    def _check_st_status(self):
        """
        检测可能的ST股（基于涨跌幅特征）
        注意: 这只是一个启发式方法，准确的ST状态需要从公告数据获取
        """
        close = self.prices['$close']
        daily_ret = close.groupby(level='instrument').pct_change() * 100
        daily_ret = daily_ret.replace([np.inf, -np.inf], np.nan)

        st_suspects = []
        for stock in self.prices.index.get_level_values('instrument').unique():
            try:
                rets = daily_ret.xs(stock, level=1)
                rets = rets.dropna()
                if len(rets) < 50:
                    continue
                near_5 = ((rets > 4.5) & (rets < 5.5)) | ((rets > -5.5) & (rets < -4.5))
                near_5_ratio = near_5.sum() / len(rets)
                if near_5_ratio > 0.3:
                    board = get_board(stock)
                    expected_limit = get_limit_pct(board)
                    if expected_limit != 0.05:
                        st_suspects.append({
                            'stock': stock,
                            'board': board.value,
                            'near_5_ratio': round(near_5_ratio * 100, 1),
                            'expected_limit': f"{expected_limit*100:.0f}%"
                        })
            except Exception as e:
                # 记录异常但不中断验证流程
                pass

        if st_suspects:
            self.issues['st_suspects'] = {
                'type': 'st_suspects',
                'count': len(st_suspects),
                'samples': st_suspects[:5],
                'severity': 'info',
                'detail': f'疑似ST股: {len(st_suspects)}只（需人工确认）'
            }

    def _check_split_events(self):
        """检测可能的股票拆分/分红事件"""
        close = self.prices['$close']
        prev_close = close.groupby(level='instrument').shift(1)
        price_ratio = close / prev_close
        price_ratio = price_ratio.replace([np.inf, -np.inf], np.nan)

        split_candidates = (price_ratio < 0.5) | (price_ratio > 2.0)
        limit_check = (price_ratio < 1.3) & (price_ratio > 0.7)
        split_candidates = split_candidates & ~limit_check

        if split_candidates.any():
            count = split_candidates.sum()
            self.issues['split_events'] = {
                'type': 'split_events',
                'count': int(count),
                'severity': 'info',
                'detail': f'疑似拆分/分红事件: {count}条'
            }

    def get_correction_recommendations(self) -> list:
        """获取数据修正建议"""
        recommendations = []

        if any('extreme' in k for k in self.issues):
            recommendations.append({
                'action': 'clip_extreme_prices',
                'description': '对>10000元的异常价格进行截断处理',
                'threshold': 10000
            })

        if any('return_violation' in k for k in self.issues):
            recommendations.append({
                'action': 'cap_returns_to_limit',
                'description': '将超出涨跌停限制的收益率裁剪到涨停/跌停价',
                'method': '根据板块限制重新计算涨停跌停价'
            })

        if 'volume_anomaly' in self.issues:
            recommendations.append({
                'action': 'clip_volume',
                'description': '对异常放大的成交量进行截断（如>3倍标准差）',
                'method': 'winsorize'
            })

        return recommendations

    def apply_corrections(self, corrections: list = None) -> pd.DataFrame:
        """
        应用数据修正
        参数:
            corrections: 修正列表，可选。None则使用自动检测的建议
        返回:
            修正后的价格DataFrame
        """
        if corrections is None:
            corrections = self.get_correction_recommendations()

        corrected = self.prices.copy()

        # 确保价格列和成交量列为浮点型，避免pandas 3.x的LossySetitemError
        for col in ['$open', '$close', '$high', '$low', '$volume']:
            if col in corrected.columns and corrected[col].dtype == 'int64':
                corrected[col] = corrected[col].astype(float)

        for corr in corrections:
            action = corr['action']

            if action == 'clip_extreme_prices':
                threshold = corr.get('threshold', 10000)
                for col in ['$open', '$close', '$high', '$low']:
                    mask = corrected[col].abs() > threshold
                    corrected.loc[mask, col] = np.sign(corrected.loc[mask, col]) * threshold

            elif action == 'cap_returns_to_limit':
                close = corrected['$close']
                prev_close = close.groupby(level='instrument').shift(1)
                for col in ['$open', '$high', '$low']:
                    limit_up, limit_down = self._calc_limit_series(prev_close)
                    corrected.loc[corrected[col] > limit_up, col] = limit_up
                    corrected.loc[corrected[col] < limit_down, col] = limit_down

            elif action == 'clip_volume':
                corrected['$volume'] = corrected['$volume'].astype(float)
                vol = corrected['$volume']
                vol_mean = vol.groupby(level='instrument').transform('mean')
                vol_std = vol.groupby(level='instrument').transform('std')
                upper = vol_mean + 3 * vol_std
                corrected.loc[corrected['$volume'] > upper, '$volume'] = upper

        return corrected

    def _calc_limit_series(self, prev_close: pd.Series) -> tuple[pd.Series, pd.Series]:
        """计算每只股票的涨跌停价序列"""
        codes = self.prices.index.get_level_values('instrument')
        limits = codes.map(lambda c: get_limit_pct(get_board(c)))
        limit_up = prev_close * (1 + limits)
        limit_down = prev_close * (1 - limits)
        return limit_up, limit_down


def validate_stock_data(prices_df: pd.DataFrame, output_path: Optional[str] = None) -> dict:
    """
    验证股票数据质量，输出报告
    参数:
        prices_df: 价格DataFrame
        output_path: 报告输出路径，可选
    返回:
        问题汇总字典
    """
    validator = DataValidator(prices_df)
    issues = validator.validate_all()

    summary = {
        'total_issues': sum(v.get('count', 0) for v in issues.values()),
        'error_count': sum(1 for v in issues.values() if v.get('severity') == 'error'),
        'warning_count': sum(1 for v in issues.values() if v.get('severity') == 'warning'),
        'info_count': sum(1 for v in issues.values() if v.get('severity') == 'info'),
        'issues': issues,
        'recommendations': validator.get_correction_recommendations(),
    }

    if output_path:
        import json
        out = {k: {kk: vv for kk, vv in v.items() if kk != 'samples'} for k, v in summary['issues'].items()}
        with open(output_path, 'w') as f:
            json.dump(out, f, indent=2, ensure_ascii=False, default=str)
        print(f"  报告已保存: {output_path}")

    return summary


def print_trading_rules_summary():
    """打印交易规则摘要"""
    print("=" * 60)
    print("  A股交易规则摘要")
    print("=" * 60)
    for board in [Board.SH_MAIN, Board.SZ_MAIN, Board.SZ_GEM, Board.SH_STAR, Board.BJ]:
        ref_code = "SH600000" if board == Board.SH_MAIN else \
                   "SZ000001" if board == Board.SZ_MAIN else \
                   "SZ300001" if board == Board.SZ_GEM else \
                   "SH688001" if board == Board.SH_STAR else "BJ920000"
        info = get_board_info(ref_code)
        print(f"\n  {info['board']}:")
        print(f"    涨跌幅: ±{info['limit_pct']:.0f}%")
        print(f"    最小交易单位: {info['lot_size']}股")

    print(f"\n  通用规则:")
    print(f"    交易制度: T+1（当日买入次日可卖出）")
    print(f"    集合竞价: 09:15-09:25")
    print(f"    连续竞价: 09:30-11:30, 13:00-15:00")
    print(f"    ST股涨跌幅: ±5%")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--rules":
        print_trading_rules_summary()
