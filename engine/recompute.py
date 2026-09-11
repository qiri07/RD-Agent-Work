#!/usr/bin/env python3
"""
因子重算 + IC分析 引擎模块
===========================
从 run_full_recompute.py 提取的公共逻辑。
提供因子重算、IC分析、年度报告、结果汇总等功能。
"""
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config as cfg
from logging_config import setup_logging

logger = __import__('logging').getLogger(__name__)


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
    logger.info(f"\nPhase 1 完成:")
    logger.info(f"  成功: {len(success)} 个因子")
    logger.info(f"  失败: {len(fail)} 个因子")
    logger.info(f"  总耗时: {elapsed:.1f}s")

    return success, fail


def _load_factor_results() -> Dict[str, pd.Series]:
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


def _load_returns() -> pd.DataFrame:
    """加载价格数据并计算 forward returns"""
    src_pq = cfg.DAILY_PV_PQ
    if not src_pq.exists():
        src_pq = cfg.DAILY_PV_FULL_PQ

    t0 = time.time()
    fpq = pd.read_parquet(src_pq)
    fpq_reset = fpq.reset_index()
    fpq_reset["return_5d"] = fpq_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)

    returns_df = (
        fpq_reset[["date", "instrument", "$close", "return_5d"]]
        .dropna()
        .set_index(["date", "instrument"])
    )
    returns_df.columns = ["$close", "return"]

    logger.info(f"收益率数据: {len(returns_df):,} 行")
    logger.info(f"日期范围: {returns_df.index.get_level_values(0).min().date()} ~ "
                f"{returns_df.index.get_level_values(0).max().date()}")
    logger.info(f"计算耗时: {time.time() - t0:.1f}s")
    return returns_df


def run_phase2_ic_analysis() -> Optional[Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """Phase 2: IC分析

    Returns:
        (ic_df, yearly_df, report) 或 None（分析失败）
    """
    from run_factor_ic_scan import ic_analysis

    logger.info("=" * 70)
    logger.info("  Phase 2: IC分析")
    logger.info("=" * 70)

    logger.info("加载因子结果...")
    factor_results = _load_factor_results()
    if not factor_results:
        logger.error("没有可用的因子结果")
        return None

    logger.info("\n计算forward returns...")
    returns_df = _load_returns()

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


def ic_analysis_yearly(factor_results: Dict[str, pd.Series],
                       returns_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """年度IC分析

    Returns:
        DataFrame with columns [factor_id, year, IC] 或 None
    """
    yearly_results = []

    for factor_id, factor_series in factor_results.items():
        factor_valid = factor_series.dropna()
        if len(factor_valid) < 1000:
            continue

        dates = factor_valid.index.get_level_values(0)
        years = dates.year.unique()

        for year in years:
            year_mask = dates == year
            year_factor = factor_valid[year_mask]
            year_returns = returns_df[returns_df.index.get_level_values(0).year == year]["return"]

            common_idx = year_factor.index.intersection(year_returns.index)
            if len(common_idx) < 100:
                continue

            f = year_factor.reindex(common_idx)
            r = year_returns.reindex(common_idx)
            ic_val = f.corr(r, method="spearman")
            if not np.isnan(ic_val):
                yearly_results.append({
                    'factor_id': factor_id,
                    'year': int(year),
                    'IC': ic_val,
                })

    if not yearly_results:
        return None
    return pd.DataFrame(yearly_results)


def generate_ic_report(ic_df: pd.DataFrame) -> pd.DataFrame:
    """生成IC综合分析报告（含年度IC稳定性指标）"""
    report_data = []

    for _, row in ic_df.iterrows():
        factor_id = row['factor_id']
        ic_5d = row.get('IC_5d', np.nan)
        ic_t_5d = row.get('IC_t_5d', np.nan)
        ic_pos = row.get('IC_pos_ratio_5d', np.nan)

        ic_2023 = row.get('IC_2023', np.nan)
        ic_2024 = row.get('IC_2024', np.nan)
        ic_2025 = row.get('IC_2025', np.nan)
        ic_2026 = row.get('IC_2026', np.nan)

        ic_values = [v for v in [ic_2023, ic_2024, ic_2025, ic_2026] if not np.isnan(v)]
        ic_mean = np.mean(ic_values) if ic_values else np.nan
        ic_std = np.std(ic_values) if len(ic_values) > 1 else 0
        ic_cv = ic_std / abs(ic_mean) if ic_mean != 0 else 999

        report_data.append({
            'factor_id': factor_id,
            'IC_5d': ic_5d,
            'IC_t_5d': ic_t_5d,
            'IC_pos_5d': ic_pos,
            'abs_IC': abs(ic_5d) if not np.isnan(ic_5d) else 0,
            'IC_mean': ic_mean,
            'IC_std': ic_std,
            'IC_cv': ic_cv,
            'ICIR': ic_mean / ic_std if ic_std > 0 else 0,
            'ic_2023': ic_2023,
            'ic_2024': ic_2024,
            'ic_2025': ic_2025,
            'ic_2026': ic_2026,
        })

    return pd.DataFrame(report_data)


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
    t_total = time.time()

    success, fail = run_phase1_recompute()
    result = run_phase2_ic_analysis()

    if result:
        ic_df, yearly_df, report = result
        print_summary(ic_df)

        summary_path = cfg.PROJECT_ROOT / "recompute_summary.json"
        import json
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
