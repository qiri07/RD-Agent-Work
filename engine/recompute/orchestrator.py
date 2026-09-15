#!/usr/bin/env python3
"""
因子重算编排模块
=================
Phase 1 重算因子，Phase 2 IC分析。
"""
import time
import logging
from typing import List, Optional, Tuple
import pandas as pd
import config as cfg
from .loader import load_factor_results, load_returns
from .ic_analysis import ic_analysis_yearly, generate_ic_report

logger = logging.getLogger(__name__)


def run_phase1_recompute() -> Tuple[List, List]:
    """Phase 1: 重算所有因子

    Returns:
        (success_list, fail_list) — 每项为 (session_name, info)
    """
    logger.info("=" * 70)
    logger.info("  Phase 1: 因子重算")
    logger.info("=" * 70)

    from batch_recompute_factors import get_sessions, copy_data_to_session, recompute_factor

    sessions = get_sessions()
    logger.info(f"找到 {len(sessions)} 个因子会话")

    # 检查数据源
    src_pq = cfg.DAILY_PV_PQ
    if not src_pq.exists():
        src_pq = cfg.DAILY_PV_FULL_CORRECTED_PQ
    if not src_pq.exists():
        src_pq = cfg.DAILY_PV_FULL_PQ

    logger.info(f"使用数据源: {src_pq}")
    logger.info(f"数据大小: {src_pq.stat().st_size / 1024 / 1024:.1f} MB")

    success, fail = [], []
    t_start = time.time()

    for i, session in enumerate(sessions, 1):
        logger.info(f"[{i}/{len(sessions)}] {session.name}")

        if copy_data_to_session(session):
            ok, info = recompute_factor(session)
            if ok:
                success.append((session.name, info))
            else:
                fail.append((session.name, info))
                logger.warning(f"  失败: {info}")

        if i % 10 == 0:
            elapsed = time.time() - t_start
            rate = i / elapsed
            eta = (len(sessions) - i) / rate
            logger.info(f"  进度: {i}/{len(sessions)}, 已用: {elapsed:.0f}s, 预计剩余: {eta:.0f}s")

    elapsed = time.time() - t_start
    logger.info("\nPhase 1 完成:")
    logger.info(f"  成功: {len(success)} 个因子")
    logger.info(f"  失败: {len(fail)} 个因子")
    logger.info(f"  总耗时: {elapsed:.1f}s")

    return success, fail


def run_phase2_ic_analysis() -> Optional[Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """Phase 2: IC分析

    Returns:
        (ic_df, yearly_df, report) 或 None（分析失败）
    """
    from engine.ic_scan import ic_analysis

    logger.info("=" * 70)
    logger.info("  Phase 2: IC分析")
    logger.info("=" * 70)

    logger.info("加载因子结果...")
    factor_results = load_factor_results()
    if not factor_results:
        logger.error("没有可用的因子结果")
        return None

    logger.info("\n计算forward returns...")
    returns_df = load_returns()

    logger.info("\n运行IC分析...")
    t0 = time.time()
    ic_df = ic_analysis(factor_results, returns_df)
    logger.info(f"IC分析耗时: {time.time() - t0:.1f}s")

    if ic_df is None or len(ic_df) == 0:
        logger.error("IC分析失败")
        return None

    # 保存结果
    logger.info("\n保存结果...")
    pq_path = cfg.FACTOR_SOURCE / "ic_scan_results_new.parquet"
    ic_df.to_parquet(pq_path)
    logger.info(f"  Parquet: {pq_path}")

    csv_path = cfg.PROJECT_ROOT / "ic_scan_results_new.csv"
    ic_df.to_csv(csv_path, index=False)
    logger.info(f"  CSV: {csv_path}")

    # 年度IC分析
    logger.info("\n分析年度IC...")
    yearly_df = ic_analysis_yearly(factor_results, returns_df)
    if yearly_df is not None:
        yearly_pq = cfg.FACTOR_SOURCE / "ic_analysis_yearly.parquet"
        yearly_df.to_parquet(yearly_pq)
        logger.info(f"  年度IC: {yearly_pq}")

    # 综合IC分析
    logger.info("\n生成分析报告...")
    report = generate_ic_report(ic_df)
    report_path = cfg.PROJECT_ROOT / "ic_analysis_comprehensive.csv"
    report.to_csv(report_path, index=False)
    logger.info(f"  综合报告: {report_path}")

    return ic_df, yearly_df, report
