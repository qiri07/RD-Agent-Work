#!/usr/bin/env python3
"""
价格处理模块
============
负责价格数据加载、复权计算、价格查找。
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import config as cfg

logger = logging.getLogger(__name__)


class PriceEngine:
    """价格处理引擎"""

    def __init__(self, source_pq: Optional[Path] = None):
        self.source_pq = source_pq or cfg.DAILY_PV_PQ
        self.split_prev = pd.Timestamp(cfg.BACKTEST_SPLIT_DATE_PREV or "2026-09-01")
        self.split_curr = pd.Timestamp(cfg.BACKTEST_SPLIT_DATE_CURR or "2026-09-02")
        self.split_ratio_threshold = cfg.BACKTEST_SPLIT_RATIO_THRESHOLD

    def load_prices(self) -> pd.DataFrame:
        """加载价格数据"""
        df = pd.read_parquet(self.source_pq)
        df.index.names = ['datetime', 'instrument']
        df = df.sort_index()
        df = df[~df.index.duplicated(keep='first')]
        return df

    def compute_adjusted_prices(self, df: Optional[pd.DataFrame] = None) -> Tuple[pd.DataFrame, List[str]]:
        """
        计算复权价格：
        - 检测拆分股票（前后收盘价比值 > 阈值）
        - 对拆分股票的拆分前价格乘以复权因子
        """
        if df is None:
            df = self.load_prices()

        # 获取拆分日前后的收盘价
        try:
            prev_close = df.xs(self.split_prev, level='datetime')['$close']
            curr_close = df.xs(self.split_curr, level='datetime')['$close']
        except KeyError:
            return df, []

        common = prev_close.index.intersection(curr_close.index)
        ratios = prev_close[common] / curr_close[common]
        split_stocks = ratios[ratios > self.split_ratio_threshold].index.tolist()

        if not split_stocks:
            return df, []

        # 创建复权价格 DataFrame
        adj = df.copy()
        mask_pre_split = df.index.get_level_values('datetime') < self.split_curr

        for stock in split_stocks:
            stock_mask = mask_pre_split & (df.index.get_level_values('instrument') == stock)
            ratio = ratios[stock]
            for col in ['$open', '$close', '$high', '$low']:
                adj.loc[stock_mask, col] = df.loc[stock_mask, col] * ratio

        return adj, split_stocks

    def build_price_map(self, df: pd.DataFrame) -> Dict[Tuple, Dict]:
        """构建快速价格查找字典"""
        price_map = {}
        for (dt, inst), row in df.iterrows():
            price_map[(dt, inst)] = {
                'open': row['$open'],
                'close': row['$close'],
                'high': row.get('$high', row['$close']),
                'low': row.get('$low', row['$close']),
            }
        return price_map

    def get_stock_prices(self, df: pd.DataFrame, stock: str, 
                         start_date=None, end_date=None) -> pd.Series:
        """获取指定股票的价格序列"""
        stock_data = df.xs(stock, level='instrument')
        if start_date:
            stock_data = stock_data[stock_data.index >= start_date]
        if end_date:
            stock_data = stock_data[stock_data.index <= end_date]
        return stock_data

    def get_returns(self, df: pd.DataFrame, stock: str, 
                    hold_days: int = 5) -> pd.Series:
        """计算持有期收益"""
        prices = self.get_stock_prices(df, stock, end_date=self.split_prev)
        if len(prices) < hold_days + 1:
            return pd.Series(dtype=float)
        returns = prices.pct_change(hold_days).shift(-hold_days)
        return returns.dropna()


def load_and_adjust_prices(source_pq: Optional[Path] = None) -> Tuple[pd.DataFrame, List[str]]:
    """便捷函数：加载并复权价格数据"""
    engine = PriceEngine(source_pq)
    return engine.compute_adjusted_prices()
