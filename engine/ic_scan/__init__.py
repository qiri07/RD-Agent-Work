#!/usr/bin/env python3
from __future__ import annotations
"""
engine/ic_scan 包公共 API
==========================
"""
import logging
import pandas as pd
from .core import (
    compute_ic,
    IC_FORWARD_DAYS,
    IC_WINSORIZE,
    IC_MIN_STOCKS_PER_DAY,
)
from .analysis import ic_analysis
from .data import load_returns_from_sessions, validate_data_consistency
from .orchestrator import run_ic_scan

# Backward compatibility: tests patch engine.ic_scan.logger
logger = logging.getLogger(__name__)

__all__ = [
    'compute_ic',
    'ic_analysis',
    'load_returns_from_sessions',
    'validate_data_consistency',
    'run_ic_scan',
    'IC_FORWARD_DAYS',
    'IC_WINSORIZE',
    'IC_MIN_STOCKS_PER_DAY',
    'logger',
]
