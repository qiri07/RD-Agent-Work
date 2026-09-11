#!/usr/bin/env python3
"""
新数据上重新运行所有因子 + IC 分析 入口脚本
==============================================
用法:
    python3 run_factor_ic_scan.py              # 完整流程
    python3 run_factor_ic_scan.py --phase1-only
    python3 run_factor_ic_scan.py --phase2-only
    python3 run_factor_ic_scan.py --dry-run
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from engine.ic_scan import run_ic_scan

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="新数据因子重算 + IC 分析")
    parser.add_argument("--phase1-only", action="store_true")
    parser.add_argument("--phase2-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_ic_scan(
        phase1_only=args.phase1_only,
        phase2_only=args.phase2_only,
        dry_run=args.dry_run,
    )
