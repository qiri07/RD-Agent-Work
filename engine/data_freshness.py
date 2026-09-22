#!/usr/bin/env python3
from __future__ import annotations
"""
数据源时效检查模块
=================
检查价格数据和因子数据的截止日，用于流水线前置校验和报告推送。
"""
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)


def get_price_data_cutoff() -> Optional[pd.Timestamp]:
    """
    读取价格数据源（daily_pv_full.parquet）的最新日期。
    使用 columns=[] 只读 index，避免加载完整数据。

    Returns:
        最新交易日 Timestamp，失败返回 None
    """
    pq = cfg.DAILY_PV_FULL_PQ
    if not pq.exists():
        logger.warning(f"价格数据不存在: {pq}")
        return None
    try:
        df = pd.read_parquet(pq, columns=[])
        latest = df.index.get_level_values(0).max()
        return latest
    except Exception as e:
        logger.warning(f"读取价格数据截止日失败: {e}")
        return None


def get_factor_data_cutoff() -> tuple[Optional[pd.Timestamp], int]:
    """
    扫描因子工作区，返回所有因子的最新数据截止日。
    从每个因子目录的 result.h5 / result.parquet 中取最后一个交易日。

    Returns:
        (最新截止日, 有效因子数)，失败返回 (None, 0)
    """
    ws = cfg.RDAGENT_WORKSPACE
    latest_dates = []
    for d in sorted(ws.iterdir()):
        if not d.is_dir():
            continue
        for fname in ("result.h5", "result.parquet"):
            fp = d / fname
            if not fp.exists():
                continue
            try:
                if fname == "result.h5":
                    s = pd.read_hdf(fp, key="data")
                else:
                    s = pd.read_parquet(fp)
                col = s.columns[0]
                dates = s[col].index.get_level_values(0)
                if len(dates) > 0:
                    latest_dates.append(dates.max())
                break
            except Exception as e:
                logger.debug(f"读取因子 {d.name} 截止日失败: {e}")
                continue

    if latest_dates:
        return max(latest_dates), len(latest_dates)
    return None, 0


def check_data_freshness() -> dict:
    """
    执行完整的数据时效检查。

    Returns:
        {
            "price_cutoff": Timestamp or None,
            "factor_cutoff": Timestamp or None,
            "factor_count": int,
            "days_lag": int (价格数据截止日与因子数据截止日的天数差),
            "freshness": str ("正常" / "有延迟" / "数据缺失"),
        }
    """
    price_cutoff = get_price_data_cutoff()
    factor_cutoff, factor_count = get_factor_data_cutoff()

    result: dict = {
        "price_cutoff": price_cutoff,
        "factor_cutoff": factor_cutoff,
        "factor_count": factor_count,
        "days_lag": None,
        "freshness": "未知",
    }

    if price_cutoff is not None and factor_cutoff is not None:
        lag = (price_cutoff.date() - factor_cutoff.date()).days
        result["days_lag"] = lag
        if lag == 0:
            result["freshness"] = "正常（数据已同步）"
        elif lag <= 3:
            result["freshness"] = f"轻微延迟（{lag} 天）"
        else:
            result["freshness"] = f"⚠️ 有延迟（{lag} 天），建议检查数据更新"
    elif price_cutoff is None:
        result["freshness"] = "⚠️ 价格数据缺失"
    elif factor_cutoff is None:
        result["freshness"] = "⚠️ 因子数据缺失"

    logger.info(
        f"数据时效: 价格截止={price_cutoff.date() if price_cutoff else 'N/A'}, "
        f"因子截止={factor_cutoff.date() if factor_cutoff else 'N/A'}, "
        f"延迟={result['days_lag']}天, 状态={result['freshness']}"
    )
    return result


if __name__ == "__main__":
    result = check_data_freshness()
    print("=" * 50)
    print("  数据时效检查")
    print("=" * 50)
    print(f"  价格数据截止: {result['price_cutoff'].date() if result['price_cutoff'] else 'N/A'}")
    print(f"  因子数据截止: {result['factor_cutoff'].date() if result['factor_cutoff'] else 'N/A'}")
    print(f"  因子数量: {result['factor_count']}")
    print(f"  数据延迟: {result['days_lag']} 天")
    print(f"  状态: {result['freshness']}")
