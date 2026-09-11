#!/usr/bin/env python3
"""
因子计算模块
============
负责因子加载、IC计算、标准化、合成。
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import config as cfg

logger = logging.getLogger(__name__)


class FactorEngine:
    """因子计算引擎"""

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = workspace or cfg.RDAGENT_WORKSPACE

    def load_factor(self, factor_id: str) -> Optional[pd.Series]:
        """
        加载单个因子数据
        
        Returns:
            Series with MultiIndex (datetime, instrument)
        """
        h5 = self.workspace / factor_id / "result.h5"
        if not h5.exists():
            logger.warning(f"因子文件不存在: {h5}")
            return None
        try:
            df = pd.read_hdf(h5, key="data")
            fname = df.columns[0]
            s = df[fname].copy()
            # 标准化索引
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

    def _normalize_index(self, series: pd.Series) -> pd.Series:
        """
        统一标准化MultiIndex命名
        
        Args:
            series: 原始序列
            
        Returns:
            标准化后的序列，index names为(datetime, instrument)
        """
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

    def load_factors(self, factor_ids: List[str]) -> Dict[str, pd.Series]:
        """批量加载因子"""
        factor_data = {}
        for fid in factor_ids:
            s = self.load_factor(fid)
            if s is not None:
                factor_data[fid] = s
        return factor_data

    def cross_section_zscore(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        横截面Z-score标准化
        
        Args:
            df: DataFrame with MultiIndex (datetime, instrument)
        
        Returns:
            标准化后的DataFrame
        """
        result = df.copy()
        for col in df.columns:
            grouped = df[col].groupby(level="datetime", sort=False)
            mean = grouped.transform('mean')
            std = grouped.transform('std')
            result[col] = (df[col] - mean) / std.replace(0, np.nan)
        return result.fillna(0)

    def compute_ic(self, factor: pd.Series, returns: pd.Series) -> float:
        """
        计算Spearman IC（秩相关系数）
        
        Args:
            factor: 因子值序列
            returns: 收益率序列
        
        Returns:
            IC值
        """
        common_idx = factor.dropna().index.intersection(returns.dropna().index)
        if len(common_idx) < 100:
            return np.nan
        
        f = factor.loc[common_idx]
        r = returns.loc[common_idx]
        
        # Spearman IC = 秩相关系数
        from scipy.stats import spearmanr
        ic, _ = spearmanr(f, r)
        return ic if np.isfinite(ic) else np.nan

    def compute_ic_time_series(self, factor: pd.Series, returns: pd.Series) -> Dict[pd.Timestamp, float]:
        """
        计算时间序列IC
        
        Returns:
            {date: ic_value}
        """
        common_idx = factor.dropna().index.intersection(returns.dropna().index)
        if len(common_idx) < 100:
            return {}
        
        f = factor.loc[common_idx]
        r = returns.loc[common_idx]
        
        ic_by_date = {}
        for date in f.index.get_level_values('datetime').unique():
            day_f = f.xs(date, level='datetime')
            day_r = r.xs(date, level='datetime')
            common_stocks = day_f.dropna().index.intersection(day_r.dropna().index)
            if len(common_stocks) < 50:
                continue
            from scipy.stats import spearmanr
            ic, _ = spearmanr(day_f[common_stocks], day_r[common_stocks])
            if np.isfinite(ic):
                ic_by_date[date] = ic
        
        return ic_by_date

    def synthesize_factors(self, 
                           factors: Dict[str, pd.Series],
                           weights: Optional[Dict[str, float]] = None,
                           method: str = 'equal') -> pd.Series:
        """
        合成多因子得分
        
        Args:
            factors: {factor_id: Series}
            weights: {factor_id: weight} (None=等权)
            method: 'equal' or 'ic_weighted'
        
        Returns:
            综合得分 Series
        """
        if not factors or len(factors) == 0:
            return pd.Series(dtype=float)
        
        # 合并因子
        combined = pd.DataFrame(factors)
        combined = combined.ffill().fillna(0)
        
        # 横截面标准化
        standardized = self.cross_section_zscore(combined)
        
        # 计算权重
        if weights is None:
            weights = {col: 1.0 / len(combined.columns) for col in combined.columns}
        
        # 加权合成
        score_cols = [f"score_{col}" for col in combined.columns]
        for col in combined.columns:
            w = weights.get(col, 0)
            if w > 0:
                standardized[f"score_{col}"] = standardized[col] * w
        
        composite = standardized[score_cols].sum(axis=1)
        return composite

    def get_top_stocks(self, 
                       scores: pd.Series, 
                       top_k: int = 10,
                       date: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """
        选取Top-K股票
        
        Args:
            scores: 综合得分 Series (MultiIndex)
            top_k: 选股数量
            date: 指定日期 (None=最新日期)
        
        Returns:
            DataFrame with rank and score
        """
        if date is None:
            date = scores.index.get_level_values('datetime').max()
        
        day_scores = scores.xs(date, level='datetime')
        day_scores = day_scores.dropna()
        if isinstance(day_scores, pd.DataFrame):
            score_col = 'composite_score' if 'composite_score' in day_scores.columns else day_scores.columns[0]
            day_scores = day_scores.sort_values(score_col, ascending=False)
            top_stocks = day_scores.head(top_k)
            result = pd.DataFrame({
                'score': top_stocks[score_col].values,
                'rank': range(1, len(top_stocks) + 1)
            })
        else:
            day_scores = day_scores.sort_values(ascending=False)
            top_stocks = day_scores.head(top_k)
            result = pd.DataFrame({
                'score': top_stocks.values,
                'rank': range(1, len(top_stocks) + 1)
            })
        return result

    def compute_factor_ic_summary(self, 
                                   factor_ids: List[str],
                                   returns: pd.Series) -> pd.DataFrame:
        """
        计算因子IC汇总统计
        
        Returns:
            DataFrame with IC statistics
        """
        results = []
        for fid in factor_ids:
            factor = self.load_factor(fid)
            if factor is None:
                continue
            
            ic_by_date = self.compute_ic_time_series(factor, returns)
            if not ic_by_date:
                continue
            
            ic_arr = np.array(list(ic_by_date.values()))
            n = len(ic_arr)
            ic_mean = np.nanmean(ic_arr)
            ic_std = np.nanstd(ic_arr) if n > 1 else 0
            ic_t = ic_mean / (ic_std / np.sqrt(max(n - 1, 1)) + 1e-10) if n > 1 else np.nan
            ic_pos = (ic_arr > 0).mean() if n > 0 else np.nan
            
            results.append({
                'factor_id': fid,
                'IC_5d': ic_mean,
                'IC_t_5d': ic_t,
                'IC_pos_5d': ic_pos,
                'n_days': n,
                'abs_IC': abs(ic_mean),
            })
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        df = df.sort_values('abs_IC', ascending=False)
        return df.reset_index(drop=True)


def create_factor_engine(workspace: Optional[Path] = None) -> FactorEngine:
    """工厂函数：创建因子引擎"""
    return FactorEngine(workspace)


def synthesize_daily_composite(
    factor_data: Dict[str, pd.Series],
    weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """
    统一的多因子合成入口：最新日横截面 Z-score + 等权合成。

    供 select_top10.py / run_pipeline.py 等上层脚本复用，
    避免各脚本重复实现相同的标准化与合成逻辑。

    Args:
        factor_data: {factor_id: Series}，Series 索引为 MultiIndex (datetime, instrument)
        weights:     {factor_id: weight}；None 表示等权

    Returns:
        DataFrame，index 为 instrument，包含：
            composite_score  — 综合得分
            rank             — 降序排名（dense）
            各因子 Z-score 列（列名为 factor_id）
    """
    if not factor_data:
        return pd.DataFrame()

    # 1. 取最新交易日
    latest_date = max(
        s.index.get_level_values("datetime").max()
        for s in factor_data.values()
    )
    logger.info(f"合成综合得分，最新交易日: {latest_date.strftime('%Y-%m-%d')}")

    # 2. 提取最新日期的因子截面
    day_series = {}
    for fid, s in factor_data.items():
        mask = s.index.get_level_values("datetime") == latest_date
        vals = s[mask].dropna()
        if len(vals) > 0:
            day_series[fid] = vals

    if not day_series:
        logger.warning("没有可用因子数据用于合成")
        return pd.DataFrame()

    logger.info(f"参与合成的因子数: {len(day_series)}，股票数: {len(day_series[next(iter(day_series))])}")

    # 3. 横截面 Z-score 标准化（单日截面）
    df = pd.DataFrame(day_series)  # index=MultiIndex(datetime, instrument), columns=factor_id
    # 提取 instrument 作为显式列，datetime 不再需要
    df = df.reset_index()
    instrument_col = "instrument"
    for col in df.columns:
        if col not in (instrument_col, "datetime"):
            mean = df[col].mean()
            std = df[col].std()
            df[col] = ((df[col] - mean) / std).fillna(0) if std > 0 else 0.0

    # 4. 等权合成
    factor_cols = [c for c in df.columns if c not in (instrument_col, "datetime")]
    if weights is None:
        weights = {fid: 1.0 / len(factor_cols) for fid in factor_cols}

    score_cols = [f"score_{fid}" for fid in factor_cols]
    for fid in factor_cols:
        w = weights.get(fid, 0)
        if w > 0:
            df[f"score_{fid}"] = df[fid] * w

    df["composite_score"] = df[score_cols].sum(axis=1)

    # 5. 排名
    df["rank"] = df["composite_score"].rank(ascending=False, method="dense").astype(int)

    # 6. 按综合得分降序排列
    df = df.sort_values("composite_score", ascending=False)

    # 列顺序: rank, instrument, composite_score, 各因子Z-score
    factor_cols = [c for c in df.columns if c not in ("rank", instrument_col, "composite_score", "datetime")]
    df = df[["rank", instrument_col, "composite_score"] + factor_cols]

    return df
