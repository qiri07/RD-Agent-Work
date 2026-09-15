#!/usr/bin/env python3
"""
stock_analyzer.py 单元测试
============================
测试 resolve_ticker, analyze_stock 等功能。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from stock_analyzer import resolve_ticker, INITIAL_CAPITAL, COMMISSION, SLIPPAGE


class TestResolveTicker(unittest.TestCase):
    """测试 resolve_ticker 函数"""

    def test_code_only(self):
        """纯6位代码"""
        result = resolve_ticker("603993")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "SH603993")

    def test_full_code(self):
        """完整代码格式"""
        result = resolve_ticker("SH603993")
        self.assertEqual(result[0], "SH603993")

    def test_chinese_name(self):
        """中文名称映射"""
        result = resolve_ticker("洛阳钼业")
        self.assertEqual(result[0], "SH603993")

    def test_unknown_ticker_raises(self):
        """未知股票应抛出异常"""
        with self.assertRaises(ValueError):
            resolve_ticker("INVALID999")

    def test_empty_string_raises(self):
        """空字符串应抛出异常"""
        with self.assertRaises(ValueError):
            resolve_ticker("")


class TestConstants(unittest.TestCase):
    """测试模块常量"""

    def test_initial_capital(self):
        """初始资金"""
        from stock_analyzer import INITIAL_CAPITAL
        self.assertEqual(INITIAL_CAPITAL, 1_000_000)

    def test_commission(self):
        """佣金率"""
        from stock_analyzer import COMMISSION
        self.assertEqual(COMMISSION, 0.0003)

    def test_slippage(self):
        """滑点"""
        from stock_analyzer import SLIPPAGE
        self.assertEqual(SLIPPAGE, 0.001)


if __name__ == '__main__':
    unittest.main()
