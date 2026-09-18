#!/usr/bin/env python3
from __future__ import annotations
"""
因子加载模块
============
负责从 HDF5 文件加载因子数据，标准化 MultiIndex。
"""
import logging
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
import config as cfg

logger = logging.getLogger(__name__)


class FactorLoader:
    """因子数据加载器"""

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = workspace or cfg.RDAGENT_WORKSPACE

    def load_factor(self, factor_id: str) -> Optional[pd.Series]:
        """
        加载单个因子数据（优先 result.h5，回退 result.parquet）

        Returns:
            Series with MultiIndex (datetime, instrument)
        """
        h5 = self.workspace / factor_id / "result.h5"
        pq = self.workspace / factor_id / "result.parquet"
        if h5.exists():
            src = h5
        elif pq.exists():
            src = pq
        else:
            logger.warning(f"因子文件不存在: {h5} 或 {pq}")
            return None
        try:
            if src.suffix == ".h5":
                df = pd.read_hdf(src, key="data")
            else:
                df = pd.read_parquet(src)
            # 处理 DataFrame 或 Series
            if isinstance(df, pd.DataFrame):
                fname = df.columns[0]
                s = df[fname].copy()
            else:
                s = df.copy()
            s = self._normalize_index(s)
            s = s.ffill().fillna(0)
            s = s[~s.index.duplicated(keep='first')]
            return s
        except pd.errors.EmptyDataError:
            logger.error(f"因子文件为空: {factor_id}")
            return None
        except Exception as e:
            logger.exception(f"加载因子失败: {factor_id}")
            return None

    def load_factors(self, factor_ids: List[str]) -> Dict[str, pd.Series]:
        """批量加载因子"""
        factor_data = {}
        for fid in factor_ids:
            s = self.load_factor(fid)
            if s is not None:
                factor_data[fid] = s
        return factor_data

    @staticmethod
    def _normalize_index(series: pd.Series) -> pd.Series:
        """统一标准化MultiIndex命名"""
        idx = series.index
        if not hasattr(idx, 'names'):
            series.index.names = ["datetime", "instrument"]
            return series

        if idx.names == ["instrument", "date"]:
            series.index = pd.MultiIndex.from_tuples(
                [(t[1], t[0]) for t in idx], names=["datetime", "instrument"]
            )
        elif idx.names == [None, None]:
            first = idx[0]
            if isinstance(first, tuple) and len(first) >= 2:
                if isinstance(first[0], str) and first[0].startswith(("SH", "SZ", "BJ")):
                    series.index = pd.MultiIndex.from_tuples(
                        [(t[1], t[0]) for t in idx], names=["datetime", "instrument"]
                    )
                else:
                    series.index.names = ["datetime", "instrument"]
            else:
                series.index.names = ["datetime", "instrument"]
        elif idx.names[0] != "datetime":
            series.index.names = ["datetime", "instrument"]

        return series
