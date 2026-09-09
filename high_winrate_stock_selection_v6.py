#!/usr/bin/env python3
"""
高胜率因子选股策略 v6 — 反转均衡版 (使用engine模块)
核心改进：
1. 加入反转因子对冲（短期反转 + 中期反转）
2. 动量/反转比例 6:4
3. 降低换手率（10日持有期）
4. 只用近期有效的因子

架构：使用 engine/ 和 factors/ 模块
"""
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from pathlib import Path
import json
import time
import sys

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg
from engine.backtest import create_backtest_engine
from engine.metrics import create_performance_analyzer
from factors.factor_selector import FactorSelector


def main():
    print("=" * 70)
    print("  高胜率因子选股策略 (v6 — 反转均衡版)")
    print("=" * 70)
    t_main = time.time()

    # ── 初始化引擎 ───────────────────────────────────────────────
    backtest_engine = create_backtest_engine(
        initial_capital=1_000_000,
        commission_rate=0.0013,
        slippage_rate=0.0,
        min_trade_value=10000,
        lot_size=100
    )
    perf_analyzer = create_performance_analyzer(1_000_000)

    TOP_K = 15
    HOLD_DAYS = 10  # v6使用更长持有期降低换手
    OUT = cfg.PROJECT_ROOT
    WS = cfg.RDAGENT_WORKSPACE
    SRC_PQ = cfg.DAILY_PV_PQ
    valid_prefixes = ['SH', 'SZ']

    # ── Step 1: 因子筛选 ─────────────────────────────────────────
    print("\n📊 步骤 1: 因子筛选（动量+反转）")
    print("-" * 70)

    ic = pd.read_csv(OUT / "ic_analysis_comprehensive.csv")
    yearly = pd.read_csv(OUT / "ic_analysis_yearly.csv")

    selector = FactorSelector(ic, yearly)
    factors = selector.select_v6_reversal(top_n=6)

    if not factors:
        print("  ⚠️  未筛选出符合条件的因子")
        return

    selected_fids = [f.factor_id for f in factors]
    selected_names = {f.factor_id: f.factor_name for f in factors}

    # 分类统计
    momentum_count = sum(1 for f in factors if f.ic_5d > 0)
    reversal_count = sum(1 for f in factors if f.ic_5d < 0)
    
    print(f"\n  ✅ 筛选出 {len(selected_fids)} 个因子（动量{momentum_count} + 反转{reversal_count}）:")
    print(f"  {'ID':<14} {'名称':<30} {'IC':>7s} {'类型':>6s}")
    print(f"  {'─'*14} {'─'*30} {'─'*7} {'─'*6}")
    for f in factors:
        fname = str(selected_names.get(f.factor_id, f.factor_id))[:28]
        ftype = "动量" if f.ic_5d > 0 else "反转"
        print(f"  {f.factor_id:<14} {fname:<30} {f.ic_5d:>+7.4f} {ftype:>6s}")

    # ── Step 2-6: 参考v3实现 ─────────────────────────────────────
    print("\n⚠️  v6版本的核心差异在于因子选择策略和持有期，")
    print(f"   详细回测逻辑请参考 high_winrate_stock_selection_v3.py")
    print(f"   v6使用 {HOLD_DAYS} 日持有期降低换手率")
    print("=" * 70)
    print("  提示: 如需完整v6功能，请使用 FactorSelector.select_v6_reversal()")
    
    return factors


if __name__ == "__main__":
    main()
