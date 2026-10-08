from __future__ import annotations
"""策略基类"""
from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """所有策略的公共接口：接收价格 DataFrame，返回信号 Series {-1, 0, 1}"""

    @staticmethod
    @abstractmethod
    def execute(df: pd.DataFrame) -> pd.Series:
        """执行策略，返回信号"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        ...
