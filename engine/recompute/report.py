#!/usr/bin/env python3
from __future__ import annotations
"""
IC 报告打印与完整流程编排模块
===============================
打印摘要、运行完整重算+IC分析流程。
"""
import time
import json
import logging
from typing import Optional, Tuple
import pandas as pd
import numpy as np
import config as cfg
from .loader import load_factor_results, load_returns
from .ic_analysis import ic_analysis_yearly, generate_ic_report

logger = logging.getLogger(__name__)


def print_summary(ic_df: pd.DataFrame) -> None:
    """打印IC分析摘要（Top 10 + 统计信息）"""
    print("\n" + "=" * 70)
    print("  IC分析结果摘要")
    print("=" * 70)

    if ic_df is None or len(ic_df) == 0:
        print("  无IC分析结果")
        return

    print("\n📊 Top 10 最强因子 (按 |IC| 排序):")
    print("-" * 70)
    print(f"  {'排名':>4}  {'因子ID':<40}  {'IC_5d':>8}  {'t统计':>8}  {'POS%':>7}")
    print(f"  {'─'*4}  {'─'*40}  {'─'*8}  {'─'*8}  {'─'*7}")

    for rank, (_, row) in enumerate(ic_df.head(10).iterrows(), 1):
        ic_val = row.get('IC_5d', np.nan)
        t_val = row.get('IC_t_5d', np.nan)
        pos_val = row.get('IC_pos_ratio_5d', np.nan)
        ic_str = f"{ic_val:>+8.4f}" if not np.isnan(ic_val) else "      N/A"
        t_str = f"{t_val:>+8.3f}" if not np.isnan(t_val) else "     N/A"
        pos_str = f"{pos_val*100:>6.1f}%" if not np.isnan(pos_val) else "    N/A"
        factor_id = str(row.get('factor_id', 'N/A'))[:38]
        print(f"  {rank:>4}  {factor_id:<40}  {ic_str}  {t_str}  {pos_str}")

    print("\n📈 统计信息:")
    print("-" * 70)
    valid_ics = ic_df['IC_5d'].dropna()
    if len(valid_ics) > 0:
        print(f"  有效因子数: {len(valid_ics)}")
        print(f"  IC均值: {valid_ics.mean():+.4f}")
        print(f"  IC标准差: {valid_ics.std():.4f}")
        print(f"  IC中位数: {valid_ics.median():+.4f}")
        print(f"  IC > 0: {(valid_ics > 0).sum()} 个 ({(valid_ics > 0).mean()*100:.1f}%)")
        print(f"  IC < 0: {(valid_ics < 0).sum()} 个 ({(valid_ics < 0).mean()*100:.1f}%)")
        print(f"  |IC| > 0.01: {(valid_ics.abs() > 0.01).sum()} 个")
        print(f"  |IC| > 0.02: {(valid_ics.abs() > 0.02).sum()} 个")


def run_full_recompute() -> Optional[Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """完整的因子重算 + IC分析流程（供外部调用）

    Returns:
        (ic_df, yearly_df, report) 或 None
    """
    from .orchestrator import run_phase1_recompute, run_phase2_ic_analysis

    t_total = time.time()

    success, fail = run_phase1_recompute()
    result = run_phase2_ic_analysis()

    if result:
        ic_df, yearly_df, report = result
        print_summary(ic_df)

        summary_path = cfg.PROJECT_ROOT / "recompute_summary.json"
        summary = {
            'total_factors': len(success) + len(fail),
            'success': len(success),
            'fail': len(fail),
            'failed_factors': [f[0] for f in fail],
            'ic_factors': len(ic_df) if ic_df is not None else 0,
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        logger.info(f"\n💾 汇总报告: {summary_path}")

    elapsed = time.time() - t_total
    logger.info(f"\n总耗时: {elapsed:.1f}s")
    return result
