#!/usr/bin/env python3
"""
绩效分析模块
============
负责回测结果分析、指标计算、报告生成。
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """绩效指标"""
    total_days: int
    total_return_pct: float
    annual_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    win_trades: int
    profit_factor: float
    final_value: float
    final_nav: float


class PerformanceAnalyzer:
    """绩效分析器"""

    def __init__(self, initial_capital: float = 1_000_000):
        self.initial_capital = initial_capital

    def analyze(self, 
                daily_value: List[Dict], 
                trades: List[Dict]) -> PerformanceMetrics:
        """
        分析回测结果
        
        Args:
            daily_value: [{'date': ..., 'value': ...}]
            trades: 交易记录列表
        
        Returns:
            PerformanceMetrics
        """
        if not daily_value:
            return PerformanceMetrics(
                total_days=0, total_return_pct=0, annual_return_pct=0,
                sharpe_ratio=0, max_drawdown_pct=0, win_rate_pct=0,
                total_trades=0, win_trades=0, profit_factor=0,
                final_value=0, final_nav=0
            )

        df = pd.DataFrame(daily_value).dropna(subset=['value'])
        if len(df) < 2:
            return PerformanceMetrics(
                total_days=len(df), total_return_pct=0, annual_return_pct=0,
                sharpe_ratio=0, max_drawdown_pct=0, win_rate_pct=0,
                total_trades=0, win_trades=0, profit_factor=0,
                final_value=float(df['value'].iloc[-1]) if len(df) > 0 else 0,
                final_nav=float(df['value'].iloc[-1] / self.initial_capital) if len(df) > 0 else 0
            )

        df = df.set_index('date').sort_index()
        nav = df['value'] / self.initial_capital

        # 基础指标
        total_return = (nav.iloc[-1] - 1) * 100
        days = (nav.index[-1] - nav.index[0]).days
        years = days / 365.25
        annual_return = ((nav.iloc[-1] / nav.iloc[0]) ** (1 / max(years, 0.01)) - 1) * 100 if years > 0 else total_return

        # 夏普比率
        daily_ret = nav.pct_change().dropna()
        sharpe = (daily_ret.mean() * 252 - 0.02) / (daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0

        # 最大回撤
        running_max = nav.cummax()
        drawdown = (nav - running_max) / running_max
        max_dd = drawdown.min() * 100

        # 交易统计
        sells = [t for t in trades if t.get('action') == 'SELL']
        wins = [t for t in sells if t.get('pnl_pct', 0) > 0]
        win_rate = len(wins) / len(sells) * 100 if sells else 0

        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = abs(np.mean([t['pnl_pct'] for t in sells if t.get('pnl_pct', 0) <= 0])) \
            if sells and len([t for t in sells if t.get('pnl_pct', 0) <= 0]) > 0 else 1
        profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')

        return PerformanceMetrics(
            total_days=len(df),
            total_return_pct=round(total_return, 2),
            annual_return_pct=round(annual_return, 2),
            sharpe_ratio=round(sharpe, 3),
            max_drawdown_pct=round(max_dd, 2),
            win_rate_pct=round(win_rate, 1),
            total_trades=len(sells),
            win_trades=len(wins),
            profit_factor=round(profit_factor, 2) if profit_factor != float('inf') else 999.99,
            final_value=round(float(df['value'].iloc[-1]), 2),
            final_nav=round(float(nav.iloc[-1]), 4)
        )

    def analyze_period(self, 
                       daily_value: List[Dict],
                       start_date, 
                       end_date) -> Dict:
        """分析指定区间的绩效"""
        df = pd.DataFrame(daily_value)
        mask = (df['date'] >= start_date) & (df['date'] <= end_date)
        subset = df[mask]
        
        if len(subset) < 2:
            return {'return': 0, 'sharpe': 0, 'max_dd': 0}
        
        values = subset['value'].values
        ret = (values[-1] / values[0] - 1) * 100
        
        # 简化计算
        return {
            'return': round(ret, 2),
            'sharpe': 0,
            'max_dd': 0
        }

    def monthly_stats(self, daily_value: List[Dict]) -> pd.DataFrame:
        """月度统计"""
        df = pd.DataFrame(daily_value).set_index('date').sort_index()
        monthly = df.groupby(df.index.to_period('M')).agg(
            start_val=('value', 'first'),
            end_val=('value', 'last')
        )
        monthly['ret'] = (monthly['end_val'] / monthly['start_val'] - 1) * 100
        return monthly.sort_index()

    def annual_stats(self, daily_value: List[Dict]) -> pd.DataFrame:
        """年度统计"""
        df = pd.DataFrame(daily_value).set_index('date').sort_index()
        df['year'] = df.index.year
        yearly = df.groupby('year').agg(
            start_val=('value', 'first'),
            end_val=('value', 'last')
        )
        yearly['ret'] = (yearly['end_val'] / yearly['start_val'] - 1) * 100
        yearly['dd'] = df.groupby('year')['value'].apply(
            lambda x: ((x / x.cummax()) - 1).min() * 100
        )
        return yearly

    def generate_report(self, 
                        metrics: PerformanceMetrics,
                        title: str = "回测报告") -> str:
        """生成文本报告"""
        lines = [
            "=" * 70,
            f"  {title}",
            "=" * 70,
            f"  回测天数:           {metrics.total_days}",
            f"  初始资金:           {self.initial_capital:,.0f} 元",
            f"  最终净值:           {metrics.final_value:,.0f} 元",
            f"  总收益率:           {metrics.total_return_pct:+.2f}%",
            f"  年化收益率:         {metrics.annual_return_pct:+.2f}%",
            f"  夏普比率:           {metrics.sharpe_ratio:.3f}",
            f"  最大回撤:           {metrics.max_drawdown_pct:.2f}%",
            f"  胜率:               {metrics.win_rate_pct:.1f}%",
            f"  总交易次数:         {metrics.total_trades}",
            f"  盈利交易:           {metrics.win_trades}",
            f"  盈亏比:             {metrics.profit_factor:.2f}",
            "=" * 70,
        ]
        return "\n".join(lines)


def create_performance_analyzer(initial_capital: float = 1_000_000) -> PerformanceAnalyzer:
    """工厂函数：创建绩效分析器"""
    return PerformanceAnalyzer(initial_capital)
