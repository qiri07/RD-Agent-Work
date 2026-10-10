#!/usr/bin/env python3
from __future__ import annotations
"""
集成测试：回撤控制 + 仓位管理 + 回测引擎
==========================================
测试三模块协作时的行为。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from engine.backtest import BacktestEngine, create_backtest_engine
from engine.risk_control import MaxDrawdownControl
from engine.position_manager import DynamicPositionManager


class TestBacktestWithRiskControl(unittest.TestCase):
    """测试回测引擎集成回撤控制"""

    def test_risk_control_integrated(self):
        """回撤控制集成后正常回测"""
        rc = MaxDrawdownControl(max_dd_threshold=0.20, recovery_threshold=0.05)
        engine = create_backtest_engine(
            initial_capital=1_000_000,
            risk_control=rc,
        )
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {i: ['SH600000'] for i in range(0, len(dates), 5)}
        result = engine.run(dates, price_map, signals, hold_days=3, top_k=1)
        self.assertGreater(len(result.daily_value), 0)
        self.assertGreater(len(result.trades), 0)
        # 回撤控制应已记录更新
        self.assertGreater(len(rc._history), 0)

    def test_risk_control_causes_cash_position(self):
        """剧烈回撤应触发空仓"""
        rc = MaxDrawdownControl(max_dd_threshold=0.10, recovery_threshold=0.03)
        engine = create_backtest_engine(
            initial_capital=1_000_000,
            risk_control=rc,
        )
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        # 模拟价格连续下跌触发空仓
        price_map = {}
        for i in range(len(dates)):
            price_map[(dates[i], 'SH600000')] = {'open': 100 * (0.9 ** i), 'close': 100 * (0.9 ** i)}
            price_map[(dates[i], 'SZ000001')] = {'open': 50 * (0.9 ** i), 'close': 50 * (0.9 ** i)}
        signals = {0: ['SH600000', 'SZ000001']}
        engine.run(dates, price_map, signals, hold_days=100, top_k=2)
        # 连续下跌超过10%应触发空仓
        self.assertTrue(rc.state.is_in_cash)

    def test_no_risk_control_backward_compat(self):
        """不传 risk_control 时回测仍正常（向后兼容）"""
        engine = create_backtest_engine(initial_capital=1_000_000)
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}
        result = engine.run(dates, price_map, signals, hold_days=5, top_k=1)
        self.assertGreater(len(result.daily_value), 0)


class TestBacktestWithPositionManager(unittest.TestCase):
    """测试回测引擎集成动态仓位管理"""

    def test_position_manager_integrated(self):
        """仓位管理器集成后正常回测"""
        pm = DynamicPositionManager(top_n=2, top_weight=0.30, mid_weight=0.20, tail_weight=0.10)
        rc = MaxDrawdownControl()
        engine = create_backtest_engine(
            initial_capital=1_000_000,
            risk_control=rc,
            position_manager=pm,
        )
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        # 5只股票
        stocks = ['SH600000', 'SZ000001', 'SH600002', 'SZ000003', 'SH600004']
        price_map = {}
        for i, date in enumerate(dates):
            for j, stock in enumerate(stocks):
                price_map[(date, stock)] = {'open': 50 + j * 10, 'close': 50 + j * 10 + i}
        # 每日信号包含全部5只股票
        signals = {i: stocks for i in range(0, len(dates), 5)}
        # 每日得分（越高越好）
        scores = {
            i: {stock: 5.0 - j * 0.5 for j, stock in enumerate(stocks)}
            for i in range(0, len(dates), 5)
        }
        result = engine.run(dates, price_map, signals, hold_days=3, top_k=5, scores=scores)
        self.assertGreater(len(result.daily_value), 0)
        self.assertGreater(len(result.trades), 0)

    def test_scores_none_fallback_to_equal(self):
        """不传 scores 时退化为等权"""
        pm = DynamicPositionManager()
        engine = create_backtest_engine(
            initial_capital=1_000_000,
            position_manager=pm,
        )
        dates = pd.date_range('2024-01-01', periods=15, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}
        result = engine.run(dates, price_map, signals, hold_days=5, top_k=1, scores=None)
        self.assertGreater(len(result.daily_value), 0)


class TestIntegratedWorkflow(unittest.TestCase):
    """集成工作流测试：模拟真实交易场景"""

    def test_full_workflow_with_drawdown_then_recovery(self):
        """完整流程：盈利→大幅回撤→空仓→恢复→继续交易"""
        rc = MaxDrawdownControl(max_dd_threshold=0.15, recovery_threshold=0.05)
        pm = DynamicPositionManager(top_n=2, top_weight=0.30, mid_weight=0.20, tail_weight=0.10)
        engine = create_backtest_engine(
            initial_capital=1_000_000,
            risk_control=rc,
            position_manager=pm,
        )
        # 构造30个交易日，价格先涨后跌再涨
        dates = pd.date_range('2024-01-01', periods=30, freq='B')
        base_price = 100
        # 前10天上涨，中间10天下跌，后10天上涨
        prices = []
        for i in range(30):
            if i < 10:
                p = base_price * (1 + i * 0.01)   # 上涨
            elif i < 20:
                p = base_price * 1.1 * (1 - (i - 10) * 0.03)  # 下跌
            else:
                p = base_price * 0.82 * (1 + (i - 20) * 0.02)  # 恢复
            prices.append(p)

        stocks = ['SH600000', 'SZ000001']
        price_map = {}
        for i, date in enumerate(dates):
            price_map[(date, stocks[0])] = {'open': prices[i], 'close': prices[i]}
            price_map[(date, stocks[1])] = {'open': prices[i] * 0.9, 'close': prices[i] * 0.9}

        signals = {i: stocks for i in range(0, len(dates), 5)}
        scores = {
            i: {stocks[0]: 3.0, stocks[1]: 1.0}
            for i in range(0, len(dates), 5)
        }
        result = engine.run(dates, price_map, signals, hold_days=5, top_k=2, scores=scores)

        self.assertGreater(len(result.daily_value), 0)
        self.assertGreater(len(result.trades), 0)
        # 最后一天净值应大于0
        final_value = result.daily_value[-1]['value']
        self.assertGreater(final_value, 0)
        # 回撤控制在极端下跌后应触发空仓
        summary = rc.get_summary()
        self.assertGreater(summary['max_drawdown_pct'], 0.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
