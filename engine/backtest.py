#!/usr/bin/env python3
"""
回测引擎模块
============
负责交易执行、资金管理、持仓管理。
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
import config as cfg

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """持仓信息"""
    stock: str
    shares: int
    entry_price: float
    entry_date: pd.Timestamp
    entry_idx: int


@dataclass
class Trade:
    """交易记录"""
    date: pd.Timestamp
    action: str  # 'BUY' or 'SELL'
    stock: str
    shares: int
    price: float
    value: float
    pnl_pct: float
    reason: str


@dataclass
class BacktestResult:
    """回测结果"""
    daily_value: List[Dict] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)
    positions_history: List[Dict] = field(default_factory=list)


class BacktestEngine:
    """回测引擎"""

    def __init__(self, 
                 initial_capital: float = cfg.BACKTEST_INITIAL_CAPITAL,
                 commission_rate: float = cfg.BACKTEST_COMMISSION_RATE,
                 slippage_rate: float = cfg.BACKTEST_SLIPPAGE_RATE,
                 min_trade_value: float = cfg.BACKTEST_MIN_TRADE_VALUE,
                 lot_size: int = 100):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.min_trade_value = min_trade_value
        self.lot_size = lot_size

    def run(self,
            dates: List[pd.Timestamp],
            price_map: Dict[Tuple, Dict],
            signals: Dict[int, List[str]],
            hold_days: int = 5,
            top_k: int = 10) -> BacktestResult:
        """
        运行回测
        
        Args:
            dates: 交易日列表
            price_map: 价格查找字典 {(date, stock): {'open': ..., 'close': ...}}
            signals: 每日选股信号 {date_idx: [stock_list]}
            hold_days: 持有天数
            top_k: 每次选股数量
        
        Returns:
            BacktestResult
        """
        cash = self.initial_capital
        positions: Dict[str, Position] = {}
        pending_sell: Dict[str, int] = {}  # stock -> sell_date_idx
        daily_value: List[Dict] = []
        trades: List[Dict] = []

        def get_value(date_idx: int, date: pd.Timestamp) -> float:
            total = cash
            for stock, pos in positions.items():
                key = (date, stock)
                if key in price_map:
                    total += pos.shares * price_map[key]['close']
            return total

        def sell_stock(stock: str, date: pd.Timestamp, date_idx: int, reason: str):
            nonlocal cash
            if stock not in positions:
                return
            key = (date, stock)
            if key not in price_map:
                return
            sell_price = price_map[key]['close']
            pos = positions[stock]
            trade_value = pos.shares * sell_price
            cost = trade_value * (self.commission_rate + self.slippage_rate)
            cash += trade_value - cost
            pnl_pct = (sell_price / pos.entry_price - 1) * 100
            trades.append({
                'date': date, 'action': 'SELL', 'stock': stock,
                'shares': pos.shares, 'price': sell_price,
                'value': trade_value, 'pnl_pct': pnl_pct, 'reason': reason
            })
            del positions[stock]
            pending_sell.pop(stock, None)

        def buy_stock(stock: str, date: pd.Timestamp, date_idx: int, value_target: float):
            nonlocal cash
            key = (date, stock)
            if key not in price_map:
                return
            buy_price = price_map[key]['open']
            if buy_price <= 0:
                return
            invest = min(value_target, cash * 0.99)
            if invest < self.min_trade_value:
                return
            shares = int(invest / buy_price / self.lot_size) * self.lot_size
            if shares <= 0:
                return
            cost = shares * buy_price * (1 + self.commission_rate + self.slippage_rate)
            if cost > cash:
                shares = int(cash / buy_price / self.lot_size) * self.lot_size
                if shares <= 0:
                    return
                cost = shares * buy_price * (1 + self.commission_rate + self.slippage_rate)
            cash -= cost
            positions[stock] = Position(
                stock=stock, shares=shares, entry_price=buy_price,
                entry_date=date, entry_idx=date_idx
            )
            trades.append({
                'date': date, 'action': 'BUY', 'stock': stock,
                'shares': shares, 'price': buy_price,
                'value': cost, 'pnl_pct': 0, 'reason': 'signal'
            })
            if hold_days > 0 and date_idx + hold_days < len(dates):
                pending_sell[stock] = date_idx + hold_days
            elif hold_days == 0 and date_idx + 1 < len(dates):
                # T+1: hold_days=0 时，次日才可卖出（不能当天卖）
                pending_sell[stock] = date_idx + 1

        # 边界检查
        if (hasattr(dates, 'empty') and dates.empty) or not price_map:
            return BacktestResult(daily_value=[], trades=[])

        # 主循环
        for i, date in enumerate(dates):
            # 到期卖出
            to_sell = [s for s, sd in pending_sell.items() if sd <= i]
            for stock in to_sell:
                sell_stock(stock, date, i, reason="hold_end")

            # 每日净值
            day_value = get_value(i, date)
            daily_value.append({
                'date': date, 'value': day_value,
                'cash': cash, 'positions': len(positions)
            })

            # 选股（T-1 信号）
            if i == 0:
                continue
            prev_idx = i - 1
            if prev_idx not in signals:
                continue
            selected = signals[prev_idx]

            # 调仓
            current_value = get_value(i, date)
            alloc_per_stock = current_value / top_k

            # 卖出不在列表中的
            for stock in list(positions.keys()):
                if stock not in selected:
                    sell_stock(stock, date, i, reason="rebalance")

            # 买入新标的
            for stock in selected:
                if stock in positions:
                    continue
                buy_stock(stock, date, i, alloc_per_stock)

        # 强制平仓
        last_date = dates[-1]
        last_idx = len(dates) - 1
        for stock in list(positions.keys()):
            sell_stock(stock, last_date, last_idx, reason="end")

        return BacktestResult(
            daily_value=daily_value,
            trades=[{k: v for k, v in t.items()} for t in trades]
        )

    def run_fixed_hold(self,
                       dates: List[pd.Timestamp],
                       price_map: Dict[Tuple, Dict],
                       target_stocks: List[str],
                       hold_days: int = 0) -> BacktestResult:
        """
        固定持仓回测（如等权买入持有）
        
        Args:
            dates: 交易日列表
            price_map: 价格查找字典
            target_stocks: 目标股票列表
            hold_days: 持有天数（0=持有至结束）
        
        Returns:
            BacktestResult
        """
        cash = self.initial_capital
        positions: Dict[str, Position] = {}
        pending_sell: Dict[str, int] = {}
        daily_value: List[Dict] = []
        trades: List[Dict] = []

        alloc_per_stock = cash / len(target_stocks)

        # 边界检查
        if (hasattr(dates, 'empty') and dates.empty) or not price_map:
            return BacktestResult(daily_value=[], trades=[])

        # 建仓
        first_date = dates[0]
        for stock in target_stocks:
            key = (first_date, stock)
            if key not in price_map or price_map[key]['open'] <= 0:
                continue
            buy_price = price_map[key]['open']
            invest = min(alloc_per_stock, cash * 0.99)
            shares = int(invest / buy_price / self.lot_size) * self.lot_size
            if shares <= 0:
                continue
            cost = shares * buy_price * (1 + self.commission_rate + self.slippage_rate)
            if cost > cash:
                continue
            cash -= cost
            positions[stock] = Position(
                stock=stock, shares=shares, entry_price=buy_price,
                entry_date=first_date, entry_idx=0
            )
            trades.append({
                'date': first_date, 'action': 'BUY', 'stock': stock,
                'shares': shares, 'price': buy_price,
                'value': cost, 'pnl_pct': 0, 'reason': 'initial'
            })
            if hold_days > 0:
                pending_sell[stock] = hold_days
            else:
                # T+1: hold_days=0 时，次日才可卖出
                pending_sell[stock] = 1

        # 每日净值
        for i, date in enumerate(dates):
            # 到期卖出
            to_sell = [s for s, sd in pending_sell.items() if sd <= i]
            for stock in to_sell:
                if stock not in positions:
                    continue
                key = (date, stock)
                if key not in price_map:
                    continue
                sell_price = price_map[key]['close']
                pos = positions[stock]
                trade_value = pos.shares * sell_price
                cost = trade_value * (self.commission_rate + self.slippage_rate)
                cash += trade_value - cost
                pnl_pct = (sell_price / pos.entry_price - 1) * 100
                trades.append({
                    'date': date, 'action': 'SELL', 'stock': stock,
                    'shares': pos.shares, 'price': sell_price,
                    'value': trade_value, 'pnl_pct': pnl_pct, 'reason': 'hold_end'
                })
                del positions[stock]
                pending_sell.pop(stock, None)

            # 净值
            total = cash
            for stock, pos in positions.items():
                key = (date, stock)
                if key in price_map:
                    total += pos.shares * price_map[key]['close']
            daily_value.append({
                'date': date, 'value': total,
                'cash': cash, 'positions': len(positions)
            })

        # 最终平仓
        last_date = dates[-1]
        for stock in list(positions.keys()):
            key = (last_date, stock)
            if key not in price_map:
                continue
            sell_price = price_map[key]['close']
            pos = positions[stock]
            trade_value = pos.shares * sell_price
            cost = trade_value * (self.commission_rate + self.slippage_rate)
            cash += trade_value - cost
            pnl_pct = (sell_price / pos.entry_price - 1) * 100
            trades.append({
                'date': last_date, 'action': 'SELL', 'stock': stock,
                'shares': pos.shares, 'price': sell_price,
                'value': trade_value, 'pnl_pct': pnl_pct, 'reason': 'end'
            })

        return BacktestResult(
            daily_value=daily_value,
            trades=[{k: v for k, v in t.items()} for t in trades]
        )


def create_backtest_engine(**kwargs) -> BacktestEngine:
    """工厂函数：创建回测引擎"""
    return BacktestEngine(**kwargs)
