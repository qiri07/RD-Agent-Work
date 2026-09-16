#!/usr/bin/env python3
"""
IC 扫描编排模块
===============
运行完整的 IC 扫描流程（因子重算 + IC分析）。
"""
import gc
import logging
import time
from typing import Optional
import pandas as pd
import config as cfg
from .core import IC_FORWARD_DAYS, IC_WINSORIZE, IC_MIN_STOCKS_PER_DAY
from .analysis import ic_analysis
from .data import load_returns_from_sessions, validate_data_consistency

logger = logging.getLogger(__name__)


def run_ic_scan(sessions=None, phase1_only: bool = False,
                phase2_only: bool = False, dry_run: bool = False) -> Optional[pd.DataFrame]:
    """运行完整的 IC 扫描流程（因子重算 + IC分析）

    Args:
        sessions: 因子会话列表（None=从 workspace 自动发现）
        phase1_only: 只运行 Phase 1（因子重算）
        phase2_only: 只运行 Phase 2（IC分析）
        dry_run: 只复制数据不重算

    Returns:
        IC 分析 DataFrame，phase1_only 时返回 None
    """
    from batch_recompute_factors import get_sessions, copy_data_to_session, recompute_factor as run_factor

    if sessions is None:
        sessions = get_sessions()

    if not sessions:
        return pd.DataFrame()

    logger.info(f"\n找到 {len(sessions)} 个因子会话")

    # Phase 1: 重算因子
    if not phase2_only:
        logger.info("\n━━━ Phase 1: 复制数据 + 重算因子 ━━━")
        success, fail = [], []
        for i, s in enumerate(sessions, 1):
            logger.info(f"\n[{i}/{len(sessions)}] {s.name}", end=" ", flush=True)
            if not dry_run:
                copy_data_to_session(s)
            ok, info = run_factor(s)
            if ok:
                success.append((s.name, info))
                logger.info(info)
            else:
                fail.append((s.name, info))
                logger.warning(info)
        logger.info(f"\nPhase 1 完成: 成功 {len(success)}, 失败 {len(fail)}")

    # Phase 2: IC 分析
    if not phase1_only:
        logger.info("\n━━━ Phase 2: IC 分析 ━━━")
        factor_results = {}
        for s in sessions:
            result_h5 = s / "result.h5"
            result_pq = s / "result.parquet"
            if result_h5.exists():
                try:
                    df = pd.read_hdf(result_h5, key="data")
                    factor_results[s.name] = df[df.columns[0]]
                except Exception as e:
                    logger.warning(f"  跳过 {s.name}: {e}")
            elif result_pq.exists():
                try:
                    df = pd.read_parquet(result_pq)
                    factor_results[s.name] = df[df.columns[0]]
                except Exception as e:
                    logger.warning(f"  跳过 {s.name}: {e}")

        logger.info(f"加载了 {len(factor_results)} 个因子结果")

        if not factor_results:
            logger.warning("  无可用因子结果，跳过 IC 分析")
            return pd.DataFrame()

        # 从各 session 的价格数据计算 forward returns（确保数据一致性）
        t0 = time.time()
        returns_df = load_returns_from_sessions(sessions)
        if returns_df.empty:
            logger.error("  无法加载收益率数据，跳过 IC 分析")
            return None

        logger.info(f"  收益率数据: {len(returns_df):,} 行 ({time.time()-t0:.1f}s)")
        logger.info(f"  日期范围: {returns_df.index.get_level_values(0).min().date()} ~ "
                     f"{returns_df.index.get_level_values(0).max().date()}")

        # 数据一致性验证
        validate_data_consistency(factor_results, returns_df)

        del returns_df
        gc.collect()

        ic_df = ic_analysis(factor_results, returns_df)

        # 输出结果
        logger.info("\n" + "=" * 70)
        logger.info("  IC 分析结果 (按 IC_avg 排序)")
        logger.info("=" * 70)
        ic_cols_show = [c for c in ic_df.columns if "IC_" in c]
        if ic_df.empty:
            logger.info("  (无有效因子)")
        else:
            logger.info(ic_df[["factor_id"] + ic_cols_show].to_string(index=False))

        # 保存
        out_pq = cfg.FACTOR_SOURCE / "ic_scan_results.parquet"
        ic_df.to_parquet(out_pq)
        out_csv = cfg.PROJECT_ROOT / "ic_scan_results.csv"
        ic_df.to_csv(out_csv, index=False)
        logger.info(f"\n结果已保存: {out_pq}, {out_csv}")

        return ic_df

    return None
