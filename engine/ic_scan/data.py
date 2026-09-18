#!/usr/bin/env python3
from __future__ import annotations
"""
IC 数据加载与一致性验证模块
=============================
从 session 加载收益率数据，验证因子与收益率的一致性。
"""
import logging
from typing import Dict
import pandas as pd

logger = logging.getLogger(__name__)


def load_returns_from_sessions(sessions: list) -> pd.DataFrame:
    """从各 session 的价格数据计算 forward returns

    确保 forward return 与因子计算使用相同的数据源，避免时空不匹配。

    Args:
        sessions: 因子会话列表

    Returns:
        DataFrame with MultiIndex (datetime, instrument), columns ['$close', 'return']
    """
    all_returns = []
    total = len(sessions)

    for i, s in enumerate(sessions, 1):
        session_pq = s / "daily_pv.parquet"
        if not session_pq.exists():
            logger.warning(f"  [{i}/{total}] {s.name}: 无 daily_pv.parquet，跳过")
            continue

        try:
            df = pd.read_parquet(session_pq)
            df_reset = df.reset_index().sort_values(['instrument', 'date']).reset_index(drop=True)

            # 计算 forward return（与因子计算使用相同的数据）
            df_reset["return_5d"] = df_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)
            df_reset["return_1d"] = df_reset.groupby("instrument")["$close"].pct_change(1).shift(-1)
            df_reset["return_3d"] = df_reset.groupby("instrument")["$close"].pct_change(3).shift(-3)

            returns_df = (
                df_reset[["date", "instrument", "$close", "return_1d", "return_3d", "return_5d"]]
                .dropna(subset=["return_1d", "return_3d", "return_5d"])
                .set_index(["date", "instrument"])
            )
            returns_df.columns = ["$close", "return_1d", "return_3d", "return_5d"]

            all_returns.append(returns_df)
            logger.info(f"  [{i}/{total}] {s.name}: {len(returns_df):,} 样本")
        except Exception as e:
            logger.warning(f"  [{i}/{total}] {s.name}: 读取失败 - {e}")

    if not all_returns:
        logger.error("无可用的收益率数据")
        return pd.DataFrame()

    # 合并所有 session 的收益率数据
    combined = pd.concat(all_returns)
    combined = combined[~combined.index.duplicated(keep='first')]
    logger.info(f"合并后收益率数据: {len(combined):,} 行")

    return combined


def validate_data_consistency(factor_results: Dict[str, pd.Series],
                              returns_df: pd.DataFrame) -> bool:
    """验证因子数据与收益率数据的一致性

    Returns:
        True 如果数据一致，False 如果有严重不匹配
    """
    all_factor_valid = []
    for factor_id, factor_series in factor_results.items():
        valid = factor_series.dropna()
        if len(valid) > 0:
            all_factor_valid.extend(valid.index.tolist())

    if not all_factor_valid:
        logger.warning("无有效因子数据")
        return False

    factor_idx = pd.MultiIndex.from_tuples(all_factor_valid, names=['datetime', 'instrument'])
    returns_idx = returns_df.dropna().index

    common = factor_idx.intersection(returns_idx)
    factor_only = factor_idx.difference(returns_idx)
    returns_only = returns_idx.difference(factor_idx)

    logger.info(f"数据一致性检查:")
    logger.info(f"  因子数据: {len(factor_idx):,} 样本")
    logger.info(f"  收益率数据: {len(returns_idx):,} 样本")
    logger.info(f"  共同样本: {len(common):,} ({len(common)/max(len(factor_idx),1)*100:.1f}%)")
    logger.info(f"  仅因子有: {len(factor_only):,}")
    logger.info(f"  仅收益率有: {len(returns_only):,}")

    # 检查时间范围
    factor_dates = factor_idx.get_level_values(0)
    return_dates = returns_idx.get_level_values(0)
    logger.info(f"  因子日期范围: {factor_dates.min().date()} ~ {factor_dates.max().date()}")
    logger.info(f"  收益率日期范围: {return_dates.min().date()} ~ {return_dates.max().date()}")

    # 如果共同样本太少，发出警告
    if len(common) < len(factor_idx) * 0.9:
        logger.warning(f"⚠️  数据匹配率低于 90%，可能影响 IC 计算结果")
        return False

    return True
