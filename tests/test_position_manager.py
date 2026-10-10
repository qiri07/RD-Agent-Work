#!/usr/bin/env python3
from __future__ import annotations
"""
动态仓位管理模块测试
=====================
测试 engine/position_manager.py — DynamicPositionManager
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.position_manager import DynamicPositionManager


class TestDynamicPositionManager(unittest.TestCase):
    """测试动态仓位管理模块"""

    def test_init_default(self):
        """默认初始化"""
        pm = DynamicPositionManager()
        self.assertEqual(pm.top_n, 3)
        self.assertEqual(pm.top_weight, 0.30)
        self.assertEqual(pm.mid_weight, 0.20)
        self.assertEqual(pm.tail_weight, 0.10)

    def test_empty_stocks(self):
        """空股票列表"""
        pm = DynamicPositionManager()
        result = pm.compute_allocations(stocks=[], scores={}, exposure=1.0)
        self.assertEqual(result, {})

    def test_zero_exposure(self):
        """零仓位时返回空"""
        pm = DynamicPositionManager()
        result = pm.compute_allocations(
            stocks=['SH600000'], scores={'SH600000': 1.0}, exposure=0.0
        )
        self.assertEqual(result, {})

    def test_equal_weights_no_scores(self):
        """无得分时等权分配"""
        pm = DynamicPositionManager()
        stocks = ['A', 'B', 'C']
        result = pm.compute_allocations(stocks=stocks, scores={}, exposure=1.0)
        # 所有股票应分配到相同权重
        values = list(result.values())
        self.assertAlmostEqual(sum(values), 1.0, places=5)
        self.assertAlmostEqual(values[0], values[1], places=5)
        self.assertAlmostEqual(values[1], values[2], places=5)

    def test_top_stocks_get_more_weight(self):
        """头部股票应获得更高权重"""
        pm = DynamicPositionManager(top_n=2, top_weight=0.40, mid_weight=0.20, tail_weight=0.10)
        scores = {
            'A': 5.0,   # top
            'B': 4.0,   # top
            'C': 2.0,   # mid
            'D': 1.0,   # tail
            'E': 0.5,   # tail
        }
        result = pm.compute_allocations(stocks=list(scores.keys()), scores=scores, exposure=1.0)
        # A, B 是 top2，应分配最多
        self.assertGreater(result['A'], result['C'])
        self.assertGreater(result['B'], result['C'])
        # 总和等于 exposure
        self.assertAlmostEqual(sum(result.values()), 1.0, places=5)

    def test_total_equals_exposure(self):
        """分配比例总和应等于 exposure"""
        pm = DynamicPositionManager(top_n=3)
        stocks = [f'SH{i:06d}' for i in range(10)]
        scores = {s: float(i) for i, s in enumerate(stocks)}
        for exposure in [0.0, 0.3, 0.6, 1.0]:
            result = pm.compute_allocations(stocks=stocks, scores=scores, exposure=exposure)
            total = sum(result.values())
            self.assertAlmostEqual(total, exposure, places=5,
                                   msg=f"exposure={exposure}, got total={total}")

    def test_min_position_filter(self):
        """最小仓位过滤"""
        pm = DynamicPositionManager(min_position_pct=0.05)
        # 100只股票，exposure=1.0，每只默认 1%
        stocks = [f'SH{i:06d}' for i in range(100)]
        scores = {s: float(i) for i, s in enumerate(stocks)}
        result = pm.compute_allocations(stocks=stocks, scores=scores, exposure=1.0)
        # 所有分配的仓位应 >= min_position_pct
        for stock, alloc in result.items():
            self.assertGreaterEqual(alloc, 0.05 - 1e-6)
        # 股票数应少于100（部分被过滤）
        self.assertLess(len(result), 100)

    def test_single_stock(self):
        """单只股票"""
        pm = DynamicPositionManager()
        result = pm.compute_allocations(
            stocks=['SH600000'],
            scores={'SH600000': 1.0},
            exposure=0.5
        )
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result['SH600000'], 0.5, places=5)

    def test_get_allocation_summary(self):
        """分配摘要"""
        pm = DynamicPositionManager()
        allocations = {'A': 0.3, 'B': 0.2, 'C': 0.1}
        summary = pm.get_allocation_summary(allocations)
        self.assertEqual(summary['n_stocks'], 3)
        self.assertAlmostEqual(summary['total_exposure'], 0.6, places=5)
        self.assertAlmostEqual(summary['max_allocation'], 0.3)
        self.assertAlmostEqual(summary['min_allocation'], 0.1)

    def test_empty_summary(self):
        """空分配摘要"""
        pm = DynamicPositionManager()
        summary = pm.get_allocation_summary({})
        self.assertEqual(summary['n_stocks'], 0)
        self.assertEqual(summary['total_exposure'], 0.0)

    def test_score_normaization_effect(self):
        """得分归一化使高分股获得更多仓位"""
        pm = DynamicPositionManager(top_n=1, top_weight=0.50, mid_weight=0.20, tail_weight=0.10)
        # 高分差场景：一个很高，其他很低
        scores = {'TOP': 10.0, 'LOW1': 0.0, 'LOW2': 0.0, 'LOW3': 0.0}
        result = pm.compute_allocations(stocks=list(scores.keys()), scores=scores, exposure=1.0)
        self.assertGreater(result['TOP'], result['LOW1'])
        self.assertGreater(result['TOP'], result['LOW2'])

    def test_negative_exposure_clamped(self):
        """负 exposure 返回空"""
        pm = DynamicPositionManager()
        result = pm.compute_allocations(stocks=['A', 'B'], scores={'A': 1, 'B': 2}, exposure=-0.5)
        self.assertEqual(result, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
