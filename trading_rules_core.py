#!/usr/bin/env python3
"""
A股交易规则核心模块
==================
定义 A股各板块枚举、涨跌幅限制、最小交易单位、涨跌停价计算等基础规则。

适用板块:
  - 沪深主板 (SH/SZ):   涨跌幅 ±10%, T+1, 100股/手
  - 创业板 (SZ300xxx):  涨跌幅 ±20%, T+1, 100股/手
  - 科创板 (SH688xxx):  涨跌幅 ±20%, T+1, 首笔200股后1股递增
  - 北交所 (BJ):         涨跌幅 ±30%, T+1, 100股/手
  - ST/*ST:             涨跌幅 ±5%, 其他规则同所属板块
"""

import numpy as np
import pandas as pd
from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════════════
# 板块枚举
# ═══════════════════════════════════════════════════════════
class Board(Enum):
    """A股板块分类"""
    SH_MAIN = "沪市主板"     # SH + 60xxxx
    SZ_MAIN = "深市主板"     # SZ + 00xxxx
    SZ_GEM  = "创业板"       # SZ + 300xxx
    SH_STAR = "科创板"       # SH + 688xxx
    BJ      = "北交所"       # BJ + 92xxxx
    UNKNOWN = "未知"


def get_board(stock_code: str) -> Board:
    """根据股票代码判断板块"""
    if stock_code.startswith("SH"):
        if stock_code.startswith("SH688"):
            return Board.SH_STAR
        return Board.SH_MAIN
    elif stock_code.startswith("SZ"):
        if stock_code.startswith("SZ300"):
            return Board.SZ_GEM
        return Board.SZ_MAIN
    elif stock_code.startswith("BJ"):
        return Board.BJ
    return Board.UNKNOWN


def get_limit_pct(board: Board, is_st: bool = False) -> float:
    """
    获取涨跌幅限制比例
    参数:
        board: 板块
        is_st: 是否ST股
    返回:
        涨跌停幅度（如 0.10 表示 ±10%）
    """
    if is_st:
        return 0.05  # ST股无论哪个板块都是 ±5%

    limit_map = {
        Board.SH_MAIN: 0.10,
        Board.SZ_MAIN: 0.10,
        Board.SZ_GEM:  0.20,
        Board.SH_STAR: 0.20,
        Board.BJ:      0.30,
    }
    return limit_map.get(board, 0.10)


def get_lot_size(board: Board) -> int:
    """获取最小交易单位（手）"""
    if board == Board.SH_STAR:
        return 200  # 科创板首笔200股，之后可1股递增
    return 100


def get_trading_hours() -> dict:
    """获取交易时间段"""
    return {
        "pre_auction_start": "09:15",
        "pre_auction_end": "09:25",
        "morning_session_start": "09:30",
        "morning_session_end": "11:30",
        "afternoon_session_start": "13:00",
        "afternoon_session_end": "15:00",
    }


# ═══════════════════════════════════════════════════════════
# 涨停价/跌停价计算
# ═══════════════════════════════════════════════════════════
def calc_limit_price(prev_close: float, board: Board, is_st: bool = False) -> tuple[float, float]:
    """
    计算涨停价和跌停价
    返回: (limit_up_price, limit_down_price)
    """
    limit_pct = get_limit_pct(board, is_st)
    limit_up = round(prev_close * (1 + limit_pct), 2)
    limit_down = round(prev_close * (1 - limit_pct), 2)
    return limit_up, limit_down


def is_limit_up(close: float, prev_close: float, board: Board, is_st: bool = False) -> bool:
    """判断是否涨停"""
    if prev_close <= 0:
        return False
    ret = (close / prev_close - 1) * 100
    limit_pct = get_limit_pct(board, is_st) * 100
    return ret >= limit_pct - 0.01  # 允许0.01%误差


def is_limit_down(close: float, prev_close: float, board: Board, is_st: bool = False) -> bool:
    """判断是否跌停"""
    if prev_close <= 0:
        return False
    ret = (close / prev_close - 1) * 100
    limit_pct = get_limit_pct(board, is_st) * 100
    return ret <= -limit_pct + 0.01


def get_board_info(stock_code: str) -> dict:
    """获取股票板块信息"""
    board = get_board(stock_code)
    return {
        'code': stock_code,
        'board': board.value,
        'board_enum': board,
        'limit_pct': get_limit_pct(board) * 100,
        'lot_size': get_lot_size(board),
        'trading_hours': get_trading_hours(),
    }
