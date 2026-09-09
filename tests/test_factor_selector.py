#!/usr/bin/env python3
"""
因子选择器测试
==============
测试 factors/factor_selector.py 的功能。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from factors.factor_selector import FactorSelector, FactorInfo


class TestFactorSelector(unittest.TestCase):
    """测试因子选择器"""
    
    def _create_test_data(self):
        """创建测试用的IC数据"""
        # IC综合数据
        ic_data = {
            'factor_id': ['fid_001', 'fid_002', 'fid_003', 'fid_004', 'fid_005'],
            'factor_name': ['Momentum_5d', 'Mean_Reversion', 'Volume_Shock', 'Intraday_Momentum', 'Volatility'],
            'IC_5d': [0.025, -0.018, 0.012, 0.022, -0.015],
            'IC_pos_5d': [0.65, 0.62, 0.58, 0.68, 0.60],
            'abs_IC': [0.025, 0.018, 0.012, 0.022, 0.015],
        }
        ic_df = pd.DataFrame(ic_data)
        
        # 年度IC数据
        yearly_data = {
            'factor_id': ['fid_001', 'fid_002', 'fid_003', 'fid_004', 'fid_005'],
            'year': [2023, 2024, 2025, 2026, 2023],
            'IC': [0.020, 0.030, 0.025, 0.022, 0.015],
        }
        yearly_df = pd.DataFrame(yearly_data)
        
        return ic_df, yearly_df
    
    def test_init(self):
        """初始化测试"""
        ic_df, yearly_df = self._create_test_data()
        selector = FactorSelector(ic_df, yearly_df)
        self.assertIsInstance(selector, FactorSelector)
    
    def test_prepare_data(self):
        """数据准备测试"""
        ic_df, yearly_df = self._create_test_data()
        selector = FactorSelector(ic_df, yearly_df)
        
        self.assertTrue(hasattr(selector, 'combined'))
        self.assertGreater(len(selector.combined), 0)
    
    def test_select_v3_stable(self):
        """v3稳健版选择测试"""
        ic_df, yearly_df = self._create_test_data()
        selector = FactorSelector(ic_df, yearly_df)
        
        factors = selector.select_v3_stable(top_n=3)
        
        self.assertIsInstance(factors, list)
        self.assertLessEqual(len(factors), 3)
        
        if factors:
            self.assertIsInstance(factors[0], FactorInfo)
            self.assertTrue(hasattr(factors[0], 'factor_id'))
            self.assertTrue(hasattr(factors[0], 'ic_5d'))
    
    def test_select_v4_balanced(self):
        """v4均衡版选择测试"""
        ic_df, yearly_df = self._create_test_data()
        selector = FactorSelector(ic_df, yearly_df)
        
        factors = selector.select_v4_balanced(top_n=4)
        
        self.assertIsInstance(factors, list)
        self.assertLessEqual(len(factors), 4)
    
    def test_select_v5_recent(self):
        """v5近期版选择测试"""
        # 需要包含2026年的数据
        ic_data = {
            'factor_id': ['fid_001', 'fid_002', 'fid_003'],
            'factor_name': ['Momentum_5d', 'Volume_Shock', 'Intraday'],
            'IC_5d': [0.025, 0.018, 0.022],
            'IC_pos_5d': [0.65, 0.62, 0.68],
            'abs_IC': [0.025, 0.018, 0.022],
        }
        ic_df = pd.DataFrame(ic_data)
        
        yearly_data = {
            'factor_id': ['fid_001', 'fid_002', 'fid_003'],
            'year': [2026, 2026, 2026],
            'IC': [0.025, 0.018, 0.022],
        }
        yearly_df = pd.DataFrame(yearly_data)
        
        selector = FactorSelector(ic_df, yearly_df)
        factors = selector.select_v5_recent(top_n=2)
        
        self.assertIsInstance(factors, list)
    
    def test_select_v6_reversal(self):
        """v6反转版选择测试"""
        # 需要包含正负IC的因子
        ic_data = {
            'factor_id': ['fid_001', 'fid_002', 'fid_003', 'fid_004'],
            'factor_name': ['Momentum_5d', 'Mean_Reversion', 'Volume', 'Intraday'],
            'IC_5d': [0.025, -0.018, 0.012, -0.015],
            'IC_pos_5d': [0.65, 0.62, 0.58, 0.60],
            'abs_IC': [0.025, 0.018, 0.012, 0.015],
        }
        ic_df = pd.DataFrame(ic_data)
        
        yearly_data = {
            'factor_id': ['fid_001', 'fid_002', 'fid_003', 'fid_004'],
            'year': [2023, 2023, 2023, 2023],
            'IC': [0.020, -0.015, 0.010, -0.012],
        }
        yearly_df = pd.DataFrame(yearly_data)
        
        selector = FactorSelector(ic_df, yearly_df)
        factors = selector.select_v6_reversal(top_n=4)
        
        self.assertIsInstance(factors, list)
        # 应该包含正负两种IC
        if len(factors) >= 2:
            ic_values = [f.ic_5d for f in factors]
            self.assertTrue(any(ic > 0 for ic in ic_values))
            self.assertTrue(any(ic < 0 for ic in ic_values))
    
    def test_factor_info_dataclass(self):
        """FactorInfo数据类测试"""
        info = FactorInfo(
            factor_id='fid_001',
            factor_name='Momentum',
            ic_5d=0.025,
            ic_pos_5d=0.65,
            ic_ir=1.5,
            ic_cv=0.5,
            weighted_ic=0.028
        )
        
        self.assertEqual(info.factor_id, 'fid_001')
        self.assertEqual(info.ic_5d, 0.025)
        self.assertEqual(info.weighted_ic, 0.028)
    
    def test_get_factors_by_name(self):
        """按名称筛选因子测试"""
        ic_df, yearly_df = self._create_test_data()
        selector = FactorSelector(ic_df, yearly_df)
        
        # 创建因子列表
        factors = [
            FactorInfo('fid_001', 'Momentum_5d', 0.025, 0.65, 1.5, 0.5, 0.028),
            FactorInfo('fid_002', 'Volume_Shock', 0.012, 0.58, 1.2, 0.6, 0.010),
            FactorInfo('fid_003', 'Intraday_Momentum', 0.022, 0.68, 1.8, 0.4, 0.025),
        ]
        
        # 筛选动量因子
        momentum_ids = selector.get_factors_by_name(factors, 'Momentum')
        self.assertEqual(len(momentum_ids), 2)
        self.assertIn('fid_001', momentum_ids)
        self.assertIn('fid_003', momentum_ids)
        
        # 筛选日内因子
        intraday_ids = selector.get_factors_by_name(factors, 'Intraday')
        self.assertEqual(len(intraday_ids), 1)
        self.assertIn('fid_003', intraday_ids)
    
    def test_empty_selection(self):
        """空选择测试"""
        ic_data = {
            'factor_id': ['fid_001'],
            'factor_name': ['Test'],
            'IC_5d': [0.001],  # 太小
            'IC_pos_5d': [0.51],  # 低于阈值
            'abs_IC': [0.001],
        }
        ic_df = pd.DataFrame(ic_data)
        
        yearly_data = {
            'factor_id': ['fid_001'],
            'year': [2023],
            'IC': [0.001],
        }
        yearly_df = pd.DataFrame(yearly_data)
        
        selector = FactorSelector(ic_df, yearly_df)
        factors = selector.select_v3_stable(top_n=5)
        
        # 因为阈值过滤，应该返回空列表
        self.assertEqual(len(factors), 0)
    
    def test_weighted_ic_calculation(self):
        """加权IC计算测试"""
        ic_data = {
            'factor_id': ['fid_001'],
            'factor_name': ['Test'],
            'IC_5d': [0.020],
            'IC_pos_5d': [0.65],
            'abs_IC': [0.020],
        }
        ic_df = pd.DataFrame(ic_data)
        
        yearly_data = []
        for year, ic in [(2023, 0.015), (2024, 0.018), (2025, 0.022), (2026, 0.025)]:
            yearly_data.append({'factor_id': 'fid_001', 'year': year, 'IC': ic})
        yearly_df = pd.DataFrame(yearly_data)
        
        selector = FactorSelector(ic_df, yearly_df)
        factors = selector.select_v3_stable(top_n=1)
        
        if factors:
            # 验证加权IC存在
            self.assertIsNotNone(factors[0].weighted_ic)
            self.assertIsInstance(factors[0].weighted_ic, float)


class TestFactorSelectorIntegration(unittest.TestCase):
    """因子选择器集成测试"""
    
    def test_full_workflow(self):
        """完整工作流程测试"""
        # 创建完整测试数据
        n_factors = 20
        ic_data = {
            'factor_id': [f'fid_{i:03d}' for i in range(n_factors)],
            'factor_name': [f'Factor_{i}' for i in range(n_factors)],
            'IC_5d': np.random.randn(n_factors) * 0.02 + 0.01,
            'IC_pos_5d': np.random.rand(n_factors) * 0.2 + 0.5,
            'abs_IC': np.abs(np.random.randn(n_factors) * 0.02 + 0.01),
        }
        ic_df = pd.DataFrame(ic_data)
        
        yearly_data = []
        for i in range(n_factors):
            for year in [2023, 2024, 2025, 2026]:
                yearly_data.append({
                    'factor_id': f'fid_{i:03d}',
                    'year': year,
                    'IC': np.random.randn() * 0.01 + 0.015
                })
        yearly_df = pd.DataFrame(yearly_data)
        
        # 测试所有版本
        selector = FactorSelector(ic_df, yearly_df)
        
        v3_factors = selector.select_v3_stable(top_n=5)
        v4_factors = selector.select_v4_balanced(top_n=5)
        v5_factors = selector.select_v5_recent(top_n=5)
        v6_factors = selector.select_v6_reversal(top_n=5)
        
        # 所有版本都应该返回列表
        self.assertIsInstance(v3_factors, list)
        self.assertIsInstance(v4_factors, list)
        self.assertIsInstance(v5_factors, list)
        self.assertIsInstance(v6_factors, list)
        
        # 所有因子信息都应该有效
        for version_name, factors in [('v3', v3_factors), ('v4', v4_factors), 
                                       ('v5', v5_factors), ('v6', v6_factors)]:
            for f in factors:
                self.assertIsInstance(f, FactorInfo)
                self.assertTrue(hasattr(f, 'factor_id'))
                self.assertTrue(hasattr(f, 'ic_5d'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
