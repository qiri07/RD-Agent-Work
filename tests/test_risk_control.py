#!/usr/bin/env python3
from __future__ import annotations
"""
最大回撤控制模块测试
=====================
测试 engine/risk_control.py — MaxDrawdownControl
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.risk_control import MaxDrawdownControl


class TestMaxDrawdownControl(unittest.TestCase):
    """测试最大回撤控制模块"""

    def test_init_default(self):
        """默认初始化"""
        rc = MaxDrawdownControl()
        self.assertEqual(rc.max_dd_threshold, 0.20)
        self.assertEqual(rc.recovery_threshold, 0.05)
        self.assertEqual(rc.state.peak_value, 1_000_000.0)
        self.assertEqual(rc.state.current_value, 1_000_000.0)
        self.assertAlmostEqual(rc.get_exposure(), 1.0)

    def test_no_drawdown_full_exposure(self):
        """无回撤时应保持满仓"""
        rc = MaxDrawdownControl()
        rc.update(1_000_000)
        self.assertAlmostEqual(rc.get_exposure(), 1.0)
        self.assertAlmostEqual(rc.state.drawdown_pct, 0.0)

    def test_small_drawdown_still_full(self):
        """小幅回撤(<10%)保持满仓"""
        rc = MaxDrawdownControl()
        rc.update(950_000)  # -5% drawdown
        exposure = rc.get_exposure()
        self.assertGreaterEqual(exposure, 0.99)
        self.assertLessEqual(exposure, 1.01)

    def test_10pct_drawdown_reduced(self):
        """回撤10%时仓位开始降低（超过阈值）"""
        rc = MaxDrawdownControl()
        rc.update(899_000)  # -10.1% drawdown，略超阈值
        exposure = rc.get_exposure()
        # 超过10%阈值，exposure 应严格小于 1.0
        self.assertLess(exposure, 1.0)

    def test_12pct_drawdown_partial_reduction(self):
        """回撤12%时应降至约80%仓位"""
        rc = MaxDrawdownControl()
        rc.update(880_000)  # -12% drawdown
        exposure = rc.get_exposure()
        # 10%~15% 区间线性：1.0 - (0.12 - 0.10) / 0.05 * 0.40 = 0.84
        self.assertAlmostEqual(exposure, 0.84, places=2)

    def test_15pct_drawdown_60_percent(self):
        """回撤15%时应降至60%仓位"""
        rc = MaxDrawdownControl()
        rc.update(850_000)  # -15% drawdown
        exposure = rc.get_exposure()
        self.assertAlmostEqual(exposure, 0.60, places=2)

    def test_18pct_drawdown_24_percent(self):
        """回撤18%时应降至约24%仓位"""
        rc = MaxDrawdownControl()
        rc.update(820_000)  # -18% drawdown
        exposure = rc.get_exposure()
        # 15%~20% 区间：0.60 - (0.18 - 0.15) / 0.05 * 0.60 = 0.24
        self.assertAlmostEqual(exposure, 0.24, places=2)

    def test_20pct_drawdown_full_cash(self):
        """回撤20%时应空仓"""
        rc = MaxDrawdownControl()
        rc.update(800_000)  # -20% drawdown
        self.assertTrue(rc.state.is_in_cash)
        self.assertEqual(rc.get_exposure(), 0.0)

    def test_over_20pct_still_cash(self):
        """超过20%回撤仍保持空仓"""
        rc = MaxDrawdownControl()
        rc.update(700_000)  # -30% drawdown
        self.assertTrue(rc.state.is_in_cash)
        self.assertEqual(rc.get_exposure(), 0.0)

    def test_recovery_from_cash(self):
        """从空仓状态恢复"""
        rc = MaxDrawdownControl(max_dd_threshold=0.20, recovery_threshold=0.05)
        # 先触发空仓
        rc.update(700_000)  # -30%
        self.assertTrue(rc.state.is_in_cash)
        # 恢复：净值回到 peak 的 96%（< 5% 回撤）
        rc.update(960_000)
        self.assertFalse(rc.state.is_in_cash)
        self.assertGreater(rc.get_exposure(), 0.0)

    def test_peak_updates_on_new_high(self):
        """创新高时峰值更新"""
        rc = MaxDrawdownControl()
        rc.update(1_100_000)  # 新高
        self.assertEqual(rc.state.peak_value, 1_100_000)
        self.assertEqual(rc.state.drawdown_pct, 0.0)

    def test_max_drawdown_tracked(self):
        """历史最大回撤正确追踪"""
        rc = MaxDrawdownControl()
        rc.update(1_000_000)
        rc.update(900_000)   # -10%
        rc.update(800_000)   # -20%
        rc.update(850_000)   # 回升但仍低于峰值
        self.assertAlmostEqual(rc.state.max_drawdown_pct, 0.20, places=4)

    def test_get_summary(self):
        """摘要方法"""
        rc = MaxDrawdownControl()
        rc.update(950_000)
        summary = rc.get_summary()
        self.assertIn('max_drawdown_pct', summary)
        self.assertIn('exposure', summary)
        self.assertIn('n_updates', summary)
        self.assertEqual(summary['n_updates'], 1)

    def test_reset(self):
        """重置状态"""
        rc = MaxDrawdownControl()
        rc.update(800_000)
        self.assertTrue(rc.state.is_in_cash)
        rc.reset()
        self.assertEqual(rc.state.peak_value, 1_000_000.0)
        self.assertFalse(rc.state.is_in_cash)
        self.assertEqual(rc.get_exposure(), 1.0)
        self.assertEqual(len(rc._history), 0)

    def test_custom_thresholds(self):
        """自定义阈值"""
        rc = MaxDrawdownControl(max_dd_threshold=0.10, recovery_threshold=0.03)
        rc.update(900_000)  # -10%
        self.assertTrue(rc.state.is_in_cash)
        rc.update(970_001)  # 回到 -2.999% 以内（严格小于 3%）
        self.assertFalse(rc.state.is_in_cash)

    def test_exposure_monotonic_decrease(self):
        """仓位随回撤增加单调递减"""
        rc = MaxDrawdownControl()
        exposures = []
        for pct in [0.0, 0.05, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]:
            rc.update(1_000_000 * (1 - pct))
            exposures.append(rc.get_exposure())
        # 非递增
        for i in range(1, len(exposures)):
            self.assertLessEqual(exposures[i], exposures[i - 1] + 1e-6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
