#!/usr/bin/env python3
"""
IC 分析模块
============
对所有因子进行 IC 分析，返回 IC 排名表。
"""
import logging
from typing import Dict
import numpy as np
import pandas as pd
from .core import IC_FORWARD_DAYS, IC_WINSORIZE, IC_MIN_STOCKS_PER_DAY, compute_ic

logger = logging.getLogger(__name__)


def ic_analysis(factor_results: Dict[str, pd.Series],
                returns_df: pd.DataFrame) -> pd.DataFrame:
    """对所有因子进行 IC 分析，返回 IC 排名表

    Args:
        factor_results: {factor_id: factor_series}
        returns_df: 包含 ['$close', 'return'] 列的 DataFrame

    Returns:
        IC 排名 DataFrame
    """
    all_results = []
    total = len(factor_results)

    for i, (factor_id, factor_series) in enumerate(factor_results.items(), 1):
        factor_series = factor_series.copy()
        # 缩尾处理
        if IC_WINSORIZE > 0:
            lower = factor_series.quantile(IC_WINSORIZE)
            upper = factor_series.quantile(1 - IC_WINSORIZE)
            factor_series = factor_series.clip(lower, upper)

        factor_valid = factor_series.dropna()
        if len(factor_valid) < 1000:
            logger.warning(f"  [{i}/{total}] {factor_id}: 有效数据不足 ({len(factor_valid)}), 跳过")
            continue

        row = {"factor_id": factor_id, "valid_rows": len(factor_valid)}

        for fd in IC_FORWARD_DAYS:
            fwd_return = returns_df.groupby("instrument")["$close"].pct_change(fd).shift(-fd)
            common_idx = factor_valid.index.intersection(fwd_return.dropna().index)
            if len(common_idx) < 1000:
                row[f"IC_{fd}d"] = np.nan
                row[f"IC_t_{fd}d"] = np.nan
                row[f"IC_pos_ratio_{fd}d"] = np.nan
                row[f"IC_abs_mean_{fd}d"] = np.nan
                continue

            f = factor_valid.reindex(common_idx)
            r = fwd_return.reindex(common_idx)
            mask = f.notna() & r.notna()
            f, r = f[mask], r[mask]

            ic_val = compute_ic(f, r, fd)
            row[f"IC_{fd}d"] = ic_val

            # t-stat
            if not np.isnan(ic_val) and len(f) > 20:
                f_dates_tmp = f.index.get_level_values(0)
                daily_ic_vals = []
                for dt_val in f_dates_tmp.unique():
                    m = f_dates_tmp == dt_val
                    fg = f[m]
                    rg = r[m]
                    if len(fg) >= IC_MIN_STOCKS_PER_DAY:
                        ic_v = fg.corr(rg, method="spearman")
                        if not pd.isna(ic_v):
                            daily_ic_vals.append(ic_v)
                daily_ic_tmp = pd.Series(daily_ic_vals)
                n_days = len(daily_ic_tmp)
                if n_days > 1:
                    ic_std = daily_ic_tmp.std()
                    t_stat = ic_val / (ic_std / np.sqrt(max(n_days - 1, 1)) + 1e-10) if ic_std > 0 else np.nan
                else:
                    t_stat = np.nan
                row[f"IC_t_{fd}d"] = t_stat
            else:
                row[f"IC_t_{fd}d"] = np.nan

            pos_ratio = (daily_ic_tmp > 0).mean() if daily_ic_tmp is not None else np.nan
            row[f"IC_pos_ratio_{fd}d"] = pos_ratio
            row[f"IC_abs_mean_{fd}d"] = daily_ic_tmp.abs().mean() if daily_ic_tmp is not None else np.nan

        all_results.append(row)
        logger.info(f"  [{i}/{total}] {factor_id}: done")

    result_df = pd.DataFrame(all_results)
    if result_df.empty:
        return result_df

    # 汇总 IC（取各 forward days 的均值）
    ic_cols = [c for c in result_df.columns
               if c.startswith("IC_") and not c.startswith("IC_t")
               and not c.startswith("IC_pos") and not c.startswith("IC_abs")]
    if ic_cols:
        result_df["IC_avg"] = result_df[ic_cols].mean(axis=1)
        result_df["IC_abs_avg"] = result_df[
            [c.replace("IC_", "IC_abs_mean_") for c in ic_cols]
        ].mean(axis=1)

    # 按 |IC_avg| 排序
    result_df = result_df.sort_values("IC_avg", key=abs, ascending=False)
    return result_df
