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

    def __init__(self, source_pq: Optional[Path] = None, split_ratio_threshold: Optional[float] = None):
        self.source_pq = source_pq or cfg.DAILY_PV_PQ
        self.split_prev = pd.Timestamp(cfg.BACKTEST_SPLIT_DATE_PREV or "2026-09-01")
        self.split_curr = pd.Timestamp(cfg.BACKTEST_SPLIT_DATE_CURR or "2026-09-02")
        if split_ratio_threshold is not None:
            self.split_ratio_threshold = split_ratio_threshold
        else:
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
        - 自动检测所有拆分事件（前后收盘价比值 > 阈值）
        - 仅对发生拆分的股票应用复权调整
        - 支持多次拆分事件
        """
        if df is None:
            df = self.load_prices()

        # 自动检测所有拆分日期及对应股票
        split_info = self._detect_split_events(df)

        if not split_info:
            return df, []

        adj = df.copy()
        all_split_stocks = set()

        for split_date, ratio, split_stocks in split_info:
            # 仅对拆分股票 + 拆分前日期 应用复权
            mask_pre = df.index.get_level_values('datetime') < split_date
            mask_stock = df.index.get_level_values('instrument').isin(split_stocks)
            mask = mask_pre & mask_stock
            for col in ['$open', '$close', '$high', '$low']:
                adj.loc[mask, col] = df.loc[mask, col] * ratio
            all_split_stocks.update(split_stocks)

        return adj, list(all_split_stocks)

    def _detect_split_events(self, df: pd.DataFrame) -> List[Tuple[pd.Timestamp, float, List[str]]]:
        """
        自动检测拆分日期（批量事件：同一天 ≥5 只股票出现价格突变）
        返回: [(split_date, avg_ratio, [stock_list]), ...]
        """
        close = df['$close']
        prev_close = close.groupby(level='instrument').shift(1)
        price_ratio = close / prev_close
        price_ratio = price_ratio.replace([np.inf, -np.inf], np.nan)

        # 找出所有极端比率的日期
        extreme = price_ratio[abs(price_ratio) > self.split_ratio_threshold]
        if len(extreme) == 0:
            return []

        # 按日期分组
        from collections import Counter
        date_counts = Counter(extreme.index.get_level_values(0))
        batch_split_dates = {dt for dt, cnt in date_counts.items() if cnt >= 5}

        events = []
        for split_date in sorted(batch_split_dates):
            day_extreme = extreme.xs(split_date, level='datetime')
            avg_ratio = day_extreme.mean()
            split_stocks = day_extreme.index.get_level_values('instrument').unique().tolist()
            events.append((split_date, avg_ratio, split_stocks))

        return events

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
        # xs on single-level match may return DataFrame; ensure Series
        if isinstance(stock_data, pd.DataFrame):
            stock_data = stock_data.iloc[:, 0] if len(stock_data.columns) == 1 else stock_data.iloc[:, 0]
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
