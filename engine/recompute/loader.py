#!/usr/bin/env python3
from __future__ import annotations
"""
因子与收益率数据加载模块
==========================
从 workspace 和 session 加载因子结果和收益率数据。
"""
import logging
import pandas as pd
import config as cfg

logger = logging.getLogger(__name__)


def load_factor_results() -> dict:
    """加载所有因子结果（h5 或 parquet）"""
    factor_results = {}
    for session in sorted(cfg.RDAGENT_WORKSPACE.iterdir()):
        if not session.is_dir():
            continue
        result_h5 = session / "result.h5"
        result_pq = session / "result.parquet"
        try:
            if result_h5.exists():
                df = pd.read_hdf(result_h5, key="data")
                factor_results[session.name] = df[df.columns[0]]
            elif result_pq.exists():
                df = pd.read_parquet(result_pq)
                factor_results[session.name] = df[df.columns[0]]
        except Exception as e:
            logger.warning(f"跳过 {session.name}: {e}")
    logger.info(f"加载了 {len(factor_results)} 个因子结果")
    return factor_results


def load_returns() -> pd.DataFrame:
    """加载价格数据并计算 forward returns（使用 session 数据确保一致性）"""
    from batch_recompute_factors import get_sessions

    sessions = get_sessions()
    all_returns = []

    for s in sessions:
        session_pq = s / "daily_pv.parquet"
        if not session_pq.exists():
            continue
        try:
            df = pd.read_parquet(session_pq)
            df_reset = df.reset_index().sort_values(['instrument', 'date']).reset_index(drop=True)
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
        except Exception as e:
            logger.warning(f"跳过 {s.name}: {e}")

    if not all_returns:
        # 降级：使用 source 全量数据
        src_pq = cfg.DAILY_PV_PQ
        if not src_pq.exists():
            src_pq = cfg.DAILY_PV_FULL_PQ
        fpq = pd.read_parquet(src_pq)
        fpq_reset = fpq.reset_index()
        fpq_reset["return_5d"] = fpq_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)
        returns_df = (
            fpq_reset[["date", "instrument", "$close", "return_5d"]]
            .dropna()
            .set_index(["date", "instrument"])
        )
        returns_df.columns = ["$close", "return"]
    else:
        combined = pd.concat(all_returns)
        combined = combined[~combined.index.duplicated(keep='first')]
        returns_df = combined

    logger.info(f"收益率数据: {len(returns_df):,} 行")
    logger.info(f"日期范围: {returns_df.index.get_level_values(0).min().date()} ~ "
                f"{returns_df.index.get_level_values(0).max().date()}")
    return returns_df
