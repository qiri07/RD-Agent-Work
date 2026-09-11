#!/usr/bin/env python3
"""
因子重算 + IC分析 入口脚本
===========================
用法: python3 run_full_recompute.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from logging_config import setup_logging
from engine.recompute import run_full_recompute

setup_logging(level="INFO", log_file=cfg.PROJECT_ROOT / "factor_recompute.log")

if __name__ == "__main__":
    run_full_recompute()
