#!/usr/bin/env python3
"""
trading_rules.py 单元测试
===========================
测试 get_board, get_limit_pct, get_lot_size, is_limit_up, is_limit_down 等函数。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from trading_rules import (
    Board,
    get_board,
    get_limit_pct,
    get_lot_size,
    is_limit_up,
    is_limit_down,
    calc_limit_price,
    get_board_info,
)


class TestBoardDetection(unittest.TestCase):
    """测试板块检测"""

    def test_sh_main(self):
        """沪市主板"""
        self.assertEqual(get_board("SH600000"), Board.SH_MAIN)
        self.assertEqual(get_board("SH601318"), Board.SH_MAIN)

    def test_sh_star(self):
        """科创板"""
        self.assertEqual(get_board("SH688001"), Board.SH_STAR)
        self.assertEqual(get_board("SH688981"), Board.SH_STAR)

    def test_sz_main(self):
        """深市主板"""
        self.assertEqual(get_board("SZ000001"), Board.SZ_MAIN)
        self.assertEqual(get_board("SZ000002"), Board.SZ_MAIN)

    def test_sz_gem(self):
        """创业板"""
        self.assertEqual(get_board("SZ300750"), Board.SZ_GEM)
        self.assertEqual(get_board("SZ300059"), Board.SZ_GEM)

    def test_bj(self):
        """北交所"""
        self.assertEqual(get_board("BJ920000"), Board.BJ)
        self.assertEqual(get_board("BJ920100"), Board.BJ)

    def test_unknown(self):
        """未知板块"""
        self.assertEqual(get_board("XX123456"), Board.UNKNOWN)
        self.assertEqual(get_board(""), Board.UNKNOWN)


class TestLimitPct(unittest.TestCase):
    """测试涨跌幅限制"""

    def test_sh_main_limit(self):
        """沪市主板 ±10%"""
        self.assertEqual(get_limit_pct(Board.SH_MAIN), 0.10)

    def test_sz_main_limit(self):
        """深市主板 ±10%"""
        self.assertEqual(get_limit_pct(Board.SZ_MAIN), 0.10)

    def test_sz_gem_limit(self):
        """创业板 ±20%"""
        self.assertEqual(get_limit_pct(Board.SZ_GEM), 0.20)

    def test_sh_star_limit(self):
        """科创板 ±20%"""
        self.assertEqual(get_limit_pct(Board.SH_STAR), 0.20)

    def test_bj_limit(self):
        """北交所 ±30%"""
        self.assertEqual(get_limit_pct(Board.BJ), 0.30)

    def test_st_sh_main(self):
        """ST股沪市主板 ±5%"""
        self.assertEqual(get_limit_pct(Board.SH_MAIN, is_st=True), 0.05)

    def test_st_sz_gem(self):
        """ST股创业板 ±5%"""
        self.assertEqual(get_limit_pct(Board.SZ_GEM, is_st=True), 0.05)

    def test_st_bj(self):
        """ST股北交所 ±5%"""
        self.assertEqual(get_limit_pct(Board.BJ, is_st=True), 0.05)

    def test_unknown_limit(self):
        """未知板块默认 ±10%"""
        self.assertEqual(get_limit_pct(Board.UNKNOWN), 0.10)


class TestLotSize(unittest.TestCase):
    """测试最小交易单位"""

    def test_sh_main_lot(self):
        """沪市主板 100股"""
        self.assertEqual(get_lot_size(Board.SH_MAIN), 100)

    def test_sz_main_lot(self):
        """深市主板 100股"""
        self.assertEqual(get_lot_size(Board.SZ_MAIN), 100)

    def test_sz_gem_lot(self):
        """创业板 100股"""
        self.assertEqual(get_lot_size(Board.SZ_GEM), 100)

    def test_bj_lot(self):
        """北交所 100股"""
        self.assertEqual(get_lot_size(Board.BJ), 100)

    def test_sh_star_lot(self):
        """科创板首笔200股"""
        self.assertEqual(get_lot_size(Board.SH_STAR), 200)


class TestCalcLimitPrice(unittest.TestCase):
    """测试涨跌停价计算"""

    def test_sh_main_limit_price(self):
        """沪市主板涨跌停价"""
        limit_up, limit_down = calc_limit_price(100.0, Board.SH_MAIN)
        self.assertAlmostEqual(limit_up, 110.0, places=2)
        self.assertAlmostEqual(limit_down, 90.0, places=2)

    def test_sz_gem_limit_price(self):
        """创业板涨跌停价"""
        limit_up, limit_down = calc_limit_price(100.0, Board.SZ_GEM)
        self.assertAlmostEqual(limit_up, 120.0, places=2)
        self.assertAlmostEqual(limit_down, 80.0, places=2)

    def test_bj_limit_price(self):
        """北交所涨跌停价"""
        limit_up, limit_down = calc_limit_price(100.0, Board.BJ)
        self.assertAlmostEqual(limit_up, 130.0, places=2)
        self.assertAlmostEqual(limit_down, 70.0, places=2)

    def test_st_limit_price(self):
        """ST股涨跌停价"""
        limit_up, limit_down = calc_limit_price(100.0, Board.SH_MAIN, is_st=True)
        self.assertAlmostEqual(limit_up, 105.0, places=2)
        self.assertAlmostEqual(limit_down, 95.0, places=2)

    def test_zero_prev_close(self):
        """零价格预处理"""
        limit_up, limit_down = calc_limit_price(0.0, Board.SH_MAIN)
        self.assertEqual(limit_up, 0.0)
        self.assertEqual(limit_down, 0.0)


class TestIsLimitUp(unittest.TestCase):
    """测试涨停判断"""

    def test_limit_up_sh(self):
        """沪市涨停"""
        self.assertTrue(is_limit_up(110.0, 100.0, Board.SH_MAIN))

    def test_not_limit_up_sh(self):
        """沪市未涨停"""
        self.assertFalse(is_limit_up(105.0, 100.0, Board.SH_MAIN))

    def test_limit_up_gem(self):
        """创业板涨停"""
        self.assertTrue(is_limit_up(120.0, 100.0, Board.SZ_GEM))

    def test_not_limit_up_gem(self):
        """创业板未涨停"""
        self.assertFalse(is_limit_up(110.0, 100.0, Board.SZ_GEM))

    def test_zero_prev_close(self):
        """零价格预处理"""
        self.assertFalse(is_limit_up(0.0, 0.0, Board.SH_MAIN))


class TestIsLimitDown(unittest.TestCase):
    """测试跌停判断"""

    def test_limit_down_sh(self):
        """沪市跌停"""
        self.assertTrue(is_limit_down(90.0, 100.0, Board.SH_MAIN))

    def test_not_limit_down_sh(self):
        """沪市未跌停"""
        self.assertFalse(is_limit_down(95.0, 100.0, Board.SH_MAIN))

    def test_limit_down_gem(self):
        """创业板跌停"""
        self.assertTrue(is_limit_down(80.0, 100.0, Board.SZ_GEM))

    def test_not_limit_down_gem(self):
        """创业板未跌停"""
        self.assertFalse(is_limit_down(90.0, 100.0, Board.SZ_GEM))

    def test_zero_prev_close(self):
        """零价格预处理"""
        self.assertFalse(is_limit_down(0.0, 0.0, Board.SH_MAIN))


class TestGetBoardInfo(unittest.TestCase):
    """测试获取板块信息"""

    def test_get_board_info_sh(self):
        """沪市板块信息"""
        info = get_board_info("SH600000")
        self.assertEqual(info['board'], '沪市主板')
        self.assertEqual(info['board_enum'], Board.SH_MAIN)
        self.assertEqual(info['limit_pct'], 10.0)
        self.assertEqual(info['lot_size'], 100)

    def test_get_board_info_bj(self):
        """北交所板块信息"""
        info = get_board_info("BJ920000")
        self.assertEqual(info['board'], '北交所')
        self.assertEqual(info['board_enum'], Board.BJ)
        self.assertEqual(info['limit_pct'], 30.0)
        self.assertEqual(info['lot_size'], 100)


if __name__ == '__main__':
    unittest.main()
