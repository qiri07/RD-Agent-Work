#!/usr/bin/env python3
"""
回测引擎详细测试
================
测试 engine/backtest.py 的所有功能，包括边界情况。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from engine.backtest import BacktestEngine, create_backtest_engine, BacktestResult, Position, Trade


class TestBacktestEngineRun(unittest.TestCase):
    """测试主回测流程"""

    def setUp(self):
        self.engine = create_backtest_engine(initial_capital=1_000_000)

    def test_run_basic(self):
        """基本回测"""
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {i: ['SH600000'] for i in range(1, len(dates), 5)}

        result = self.engine.run(dates, price_map, signals, hold_days=5, top_k=1)
        self.assertIsInstance(result, BacktestResult)
        self.assertGreater(len(result.daily_value), 0)
        self.assertGreater(len(result.trades), 0)

    def test_run_no_signals(self):
        """无信号回测"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100}
            for i in range(len(dates))
        }

        result = self.engine.run(dates, price_map, {}, hold_days=5, top_k=1)
        self.assertEqual(len(result.trades), 0)

    def test_run_insufficient_cash(self):
        """资金不足"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 1_000_000, 'close': 1_000_000}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}

        # 低价买入，高价卖出
        engine = create_backtest_engine(initial_capital=100_000, min_trade_value=50_000)
        result = engine.run(dates, price_map, signals, hold_days=1, top_k=1)
        # 可能无法买入（价格太高）
        self.assertIsInstance(result, BacktestResult)

    def test_run_price_not_found(self):
        """价格不存在时跳过"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        # 信号包含不在价格映射中的股票
        signals = {0: ['SH999999']}

        result = self.engine.run(dates, price_map, signals, hold_days=5, top_k=1)
        self.assertIsInstance(result, BacktestResult)

    def test_run_zero_price(self):
        """零价格时跳过买入"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 0, 'close': 100}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}

        result = self.engine.run(dates, price_map, signals, hold_days=1, top_k=1)
        # open=0 时应跳过买入
        buy_trades = [t for t in result.trades if t['action'] == 'BUY']
        self.assertEqual(len(buy_trades), 0)

    def test_run_negative_price(self):
        """负价格时跳过买入"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': -10, 'close': 100}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}

        result = self.engine.run(dates, price_map, signals, hold_days=1, top_k=1)
        buy_trades = [t for t in result.trades if t['action'] == 'BUY']
        self.assertEqual(len(buy_trades), 0)


class TestBacktestEngineHoldDays(unittest.TestCase):
    """测试持有天数逻辑"""

    def setUp(self):
        self.engine = create_backtest_engine(initial_capital=1_000_000)

    def test_hold_days_zero(self):
        """hold_days=0 时遵守T+1规则：次日才可卖出"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}

        result = self.engine.run(dates, price_map, signals, hold_days=0, top_k=1)
        buys = [t for t in result.trades if t['action'] == 'BUY']
        sells = [t for t in result.trades if t['action'] == 'SELL']
        self.assertEqual(len(buys), 1)
        self.assertGreater(len(sells), 0)
        # T+1: 卖出日期必须 >= 买入日期+1
        buy_date = buys[0]['date']
        sell_dates = [t['date'] for t in sells]
        for sd in sell_dates:
            self.assertGreaterEqual(sd, buy_date + pd.Timedelta(days=1))

    def test_hold_days_small(self):
        """短持有期"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}

        result = self.engine.run(dates, price_map, signals, hold_days=2, top_k=1)
        sells = [t for t in result.trades if t['action'] == 'SELL']
        self.assertGreater(len(sells), 0)

    def test_hold_expiry(self):
        """持有到期卖出"""
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}

        result = self.engine.run(dates, price_map, signals, hold_days=5, top_k=1)
        
        # 找到买入交易
        buy_trade = [t for t in result.trades if t['action'] == 'BUY'][0]
        # 找到对应的卖出交易
        sell_trade = [t for t in result.trades 
                      if t['action'] == 'SELL' and t['stock'] == 'SH600000'][0]
        
        buy_idx = dates.tolist().index(buy_trade['date'])
        sell_idx = dates.tolist().index(sell_trade['date'])
        
        # 卖出应在买入后约5天
        self.assertGreaterEqual(sell_idx - buy_idx, 5)


class TestBacktestEngineRebalance(unittest.TestCase):
    """测试调仓逻辑"""

    def setUp(self):
        self.engine = create_backtest_engine(initial_capital=1_000_000)

    def test_rebalance_sell_removed(self):
        """调仓时卖出不再选中的股票"""
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        # SZ000001 需要所有日期的价格（第5天才会买入）
        for i in range(len(dates)):
            price_map[(dates[i], 'SZ000001')] = {'open': 50, 'close': 50}
        
        # 第0天选SH600000，第5天选SZ000001
        signals = {
            0: ['SH600000'],
            5: ['SZ000001'],
        }

        result = self.engine.run(dates, price_map, signals, hold_days=10, top_k=1)
        
        # 应有两次买入（SH600000和SZ000001各一次）
        buys = [t for t in result.trades if t['action'] == 'BUY']
        self.assertEqual(len(buys), 2)
        
        # 应有卖出交易（调仓时卖出SH600000）
        sells = [t for t in result.trades if t['action'] == 'SELL']
        self.assertGreater(len(sells), 0)

    def test_rebalance_keep_in_list(self):
        """调仓时保留仍在列表中的股票"""
        dates = pd.date_range('2024-01-01', periods=20, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        
        signals = {
            0: ['SH600000'],
            5: ['SH600000'],  # 保持相同
        }

        result = self.engine.run(dates, price_map, signals, hold_days=10, top_k=1)
        
        # 只应买入一次
        buys = [t for t in result.trades if t['action'] == 'BUY']
        self.assertEqual(len(buys), 1)


class TestBacktestEngineFixedHold(unittest.TestCase):
    """测试固定持仓回测"""

    def setUp(self):
        self.engine = create_backtest_engine(initial_capital=1_000_000)

    def test_fixed_hold_basic(self):
        """基本固定持仓"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }

        result = self.engine.run_fixed_hold(dates, price_map, ['SH600000'], hold_days=0)
        self.assertIsInstance(result, BacktestResult)
        self.assertGreater(len(result.daily_value), 0)
        # T+1: 首日买入的股票不能在首日卖出
        buys = [t for t in result.trades if t['action'] == 'BUY']
        sells = [t for t in result.trades if t['action'] == 'SELL']
        if buys and sells:
            buy_date = buys[0]['date']
            for s in sells:
                self.assertGreater(s['date'], buy_date)

    def test_t1_violation_prevented(self):
        """T+1 规则：当天买入不能当天卖出"""
        dates = pd.date_range('2024-01-01', periods=3, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}

        result = self.engine.run(dates, price_map, signals, hold_days=0, top_k=1)
        buys = [t for t in result.trades if t['action'] == 'BUY']
        sells = [t for t in result.trades if t['action'] == 'SELL']
        if buys and sells:
            # 买和卖不能在同一天
            buy_dates = {t['date'] for t in buys}
            sell_dates = {t['date'] for t in sells}
            self.assertEqual(buy_dates & sell_dates, set())

    def test_fixed_hold_multiple_stocks(self):
        """多股票固定持仓"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {}
        for stock in ['SH600000', 'SZ000001']:
            for i in range(len(dates)):
                price_map[(dates[i], stock)] = {'open': 100, 'close': 100 + i}

        result = self.engine.run_fixed_hold(dates, price_map, ['SH600000', 'SZ000001'], hold_days=0)
        
        # 应买入两只股票
        buys = [t for t in result.trades if t['action'] == 'BUY']
        self.assertEqual(len(buys), 2)

    def test_fixed_hold_with_sell(self):
        """带卖出的固定持仓"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }

        result = self.engine.run_fixed_hold(dates, price_map, ['SH600000'], hold_days=5)
        
        sells = [t for t in result.trades if t['action'] == 'SELL']
        self.assertGreater(len(sells), 0)

    def test_fixed_hold_empty_dates(self):
        """空日期列表"""
        result = self.engine.run_fixed_hold([], {}, ['SH600000'], hold_days=0)
        self.assertEqual(len(result.daily_value), 0)

    def test_fixed_hold_price_not_found(self):
        """价格不存在时跳过"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        price_map = {}  # 空价格映射
        
        result = self.engine.run_fixed_hold(dates, price_map, ['SH600000'], hold_days=0)
        self.assertEqual(len(result.trades), 0)

    def test_fixed_hold_zero_shares(self):
        """零股数时跳过"""
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        price_map = {
            (dates[0], 'SH600000'): {'open': 1_000_000, 'close': 1_000_000}
        }
        
        # 高价导致无法买入整手
        engine = create_backtest_engine(initial_capital=10_000, lot_size=100)
        result = engine.run_fixed_hold(dates, price_map, ['SH600000'], hold_days=0)
        self.assertEqual(len(result.trades), 0)


class TestBacktestEngineEndLiquidation(unittest.TestCase):
    """测试结束平仓"""

    def setUp(self):
        self.engine = create_backtest_engine(initial_capital=1_000_000)

    def test_end_liquidation(self):
        """结束时应强制平仓"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}

        result = self.engine.run(dates, price_map, signals, hold_days=100, top_k=1)
        
        # 应有平仓交易
        end_sells = [t for t in result.trades if t.get('reason') == 'end']
        self.assertGreater(len(end_sells), 0)

    def test_final_value_equals_cash(self):
        """最终净值应等于现金"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        price_map = {
            (dates[i], 'SH600000'): {'open': 100, 'close': 100 + i}
            for i in range(len(dates))
        }
        signals = {0: ['SH600000']}

        result = self.engine.run(dates, price_map, signals, hold_days=1, top_k=1)
        
        # 最后一条记录的value应等于cash
        last_day = result.daily_value[-1]
        self.assertAlmostEqual(last_day['value'], last_day['cash'])


class TestBacktestEngineCommissionSlippage(unittest.TestCase):
    """测试手续费和滑点"""

    def test_commission_deducted(self):
        """手续费应从现金扣除"""
        engine = create_backtest_engine(
            initial_capital=1_000_000,
            commission_rate=0.001,
            slippage_rate=0.001
        )
        
        dates = pd.date_range('2024-01-01', periods=5, freq='B')
        price_map = {
            (dates[0], 'SH600000'): {'open': 100, 'close': 100}
        }
        # 需要后续日期的价格（i=1时查询T-1信号）
        for i in range(1, len(dates)):
            price_map[(dates[i], 'SH600000')] = {'open': 100, 'close': 100}
        signals = {0: ['SH600000']}

        result = engine.run(dates, price_map, signals, hold_days=1, top_k=1)
        
        buys = [t for t in result.trades if t['action'] == 'BUY']
        self.assertGreater(len(buys), 0)
        # 买入成本应包含手续费
        self.assertGreater(buys[0]['value'], 100 * buys[0]['shares'])


class TestBacktestEngineDataClasses(unittest.TestCase):
    """测试数据类"""

    def test_position_dataclass(self):
        """Position数据类"""
        pos = Position(
            stock='SH600000',
            shares=100,
            entry_price=100.0,
            entry_date=pd.Timestamp('2024-01-01'),
            entry_idx=0
        )
        self.assertEqual(pos.stock, 'SH600000')
        self.assertEqual(pos.shares, 100)

    def test_trade_dataclass(self):
        """Trade数据类"""
        trade = Trade(
            date=pd.Timestamp('2024-01-01'),
            action='BUY',
            stock='SH600000',
            shares=100,
            price=100.0,
            value=10000.0,
            pnl_pct=0.0,
            reason='signal'
        )
        self.assertEqual(trade.action, 'BUY')
        self.assertEqual(trade.pnl_pct, 0.0)

    def test_backtest_result_dataclass(self):
        """BacktestResult数据类"""
        result = BacktestResult(
            daily_value=[{'date': '2024-01-01', 'value': 1_000_000}],
            trades=[{'date': '2024-01-01', 'action': 'BUY'}]
        )
        self.assertEqual(len(result.daily_value), 1)
        self.assertEqual(len(result.trades), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
