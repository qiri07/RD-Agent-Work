#!/usr/bin/env python3
from __future__ import annotations
"""
股票分析器常量配置
==================
"""
import config as cfg
from pathlib import Path

# 数据源
SRC_PQ = cfg.DAILY_PV_FULL_PQ
if not SRC_PQ.exists():
    SRC_PQ = cfg.DAILY_PV_FULL_CORRECTED_PQ

# 回测参数
INITIAL_CAPITAL = 1_000_000
COMMISSION = 0.0003
SLIPPAGE = 0.001

# 常用股票中文名→代码映射
CODE_MAP = {
    '中国建筑': 'SH601668',
    '分众传媒': 'SZ002027',
    '贵州茅台': 'SH600519',
    '平安银行': 'SZ000001',
    '宁德时代': 'SZ300750',
    '比亚迪': 'SZ002594',
    '招商银行': 'SH600036',
    '万科A': 'SZ000002',
    '格力电器': 'SZ000651',
    '中国平安': 'SH601318',
    '海天味业': 'SH603288',
    '伊利股份': 'SH600887',
    '隆基绿能': 'SH601012',
    '药明康德': 'SH603259',
    '恒瑞医药': 'SH600276',
    '洛阳钼业': 'SH603993',
}
