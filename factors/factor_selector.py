#!/usr/bin/env python3
"""
因子选择器模块
==============
提供多种因子筛选策略，支持不同版本的选股需求。
"""
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FactorInfo:
    """因子信息"""
    factor_id: str
    factor_name: str
    ic_5d: float
    ic_pos_5d: float
    ic_ir: float
    ic_cv: float
    weighted_ic: float = 0.0


class FactorSelector:
    """因子选择器"""
    
    def __init__(self, ic_df: pd.DataFrame, yearly_df: pd.DataFrame):
        """
        参数:
            ic_df: IC综合分析结果
            yearly_df: 年度IC数据
        """
        self.ic_df = ic_df.copy()
        self.yearly_df = yearly_df.copy()
        self._prepare_data()
    
    def _prepare_data(self):
        """准备数据，计算统计量"""
        # 处理IC数据
        self.ic_df['ic_key'] = self.ic_df['IC_5d'].round(4)
        self.ic_df = self.ic_df.drop_duplicates(subset='ic_key', keep='first')
        
        # 处理年度数据
        yearly_pivot = self.yearly_df.pivot(
            index='factor_id', 
            columns='year', 
            values='IC'
        ).reset_index()
        yearly_pivot = yearly_pivot.fillna(0)
        
        # 转换列名
        for col in yearly_pivot.columns:
            if isinstance(col, str) and col.isdigit():
                yearly_pivot = yearly_pivot.rename(columns={col: int(col)})
        
        # 计算统计量
        year_cols = [c for c in yearly_pivot.columns if isinstance(c, int)]
        if year_cols:
            yearly_pivot['ic_mean'] = yearly_pivot[year_cols].mean(axis=1)
            yearly_pivot['ic_std'] = yearly_pivot[year_cols].std(axis=1)
            yearly_pivot['ic_cv'] = yearly_pivot.apply(
                lambda r: r['ic_std'] / abs(r['ic_mean']) if r['ic_mean'] != 0 else 999,
                axis=1
            )
        
        # 合并数据
        self.combined = self.ic_df.merge(yearly_pivot, on='factor_id', how='left')
        self.combined['ICIR'] = self.combined['ic_mean'] / self.combined['ic_std'].replace(0, np.nan)
    
    def select_v3_stable(self, top_n: int = 8) -> List[FactorInfo]:
        """
        v3策略：稳健增强版
        - IC变异系数 < 0.8（排除过拟合因子）
        - 近期加权IC（2025-2026权重加倍）
        - ICIR过滤
        """
        # 筛选标准
        selected = self.combined[
            (self.combined['abs_IC'] >= 0.015) &
            (self.combined['IC_pos_5d'] >= 0.6) &
            (self.combined['ic_cv'] <= 0.8) &
            (self.combined['ICIR'] >= 0.5)
        ].sort_values('ICIR', ascending=False)
        
        # 放宽条件
        if len(selected) < top_n:
            selected = self.combined[
                (self.combined['abs_IC'] >= 0.015) &
                (self.combined['IC_pos_5d'] >= 0.6) &
                (self.combined['ic_cv'] <= 1.0) &
                (self.combined['ICIR'] >= 0.3)
            ].sort_values('ICIR', ascending=False)
        
        return self._build_factor_info(selected.head(top_n))
    
    def select_v4_balanced(self, top_n: int = 8) -> List[FactorInfo]:
        """
        v4策略：均衡增强版
        - 动量组 + 反转组 + 波动率组
        - ICIR + 稳定性双重筛选
        """
        selected = self.combined[
            (self.combined['abs_IC'] >= 0.01) &
            (self.combined['IC_pos_5d'] >= 0.55) &
            (self.combined['ICIR'] >= 0.3)
        ].sort_values('ICIR', ascending=False)
        
        all_factors = selected.head(20)
        
        # 选择不同类别的因子
        momentum_fids = all_factors[
            all_factors['factor_name'].str.contains('Momentum|momentum', case=False, na=False)
        ]['factor_id'].tolist()[:3]
        
        intraday_fids = all_factors[
            all_factors['factor_name'].str.contains('intraday|Intraday', case=False, na=False)
        ]['factor_id'].tolist()[:3]
        
        other_fids = [
            f for f in all_factors['factor_id'].tolist()
            if f not in momentum_fids + intraday_fids
        ][:4]
        
        selected_fids = (momentum_fids + intraday_fids + other_fids)[:top_n]
        selected = self.combined[self.combined['factor_id'].isin(selected_fids)]
        
        return self._build_factor_info(selected)
    
    def select_v5_recent(self, top_n: int = 7) -> List[FactorInfo]:
        """
        v5策略：近期有效版
        - 完全基于2026年IC筛选
        - 只用近期有效的因子
        """
        year_cols = [c for c in self.combined.columns if isinstance(c, int)]
        if 2026 not in year_cols:
            return []
        
        recent_strong = self.combined[
            (self.combined[2026].abs() >= 0.015) &
            (self.combined['IC_pos_5d'] >= 0.6)
        ].sort_values(2026, ascending=False)
        
        # 选择不同类别
        momentum_pos = recent_strong[recent_strong[2026] > 0].head(3)
        intraday = recent_strong[
            recent_strong['factor_name'].str.contains('intraday|Intraday', case=False, na=False)
        ].head(2)
        volume = recent_strong[
            recent_strong['factor_name'].str.contains('volume|Volume', case=False, na=False)
        ].head(2)
        reversal = recent_strong[recent_strong[2026] < 0].head(1)
        
        selected = pd.concat([momentum_pos, intraday, volume, reversal]).drop_duplicates(subset='factor_id')
        
        return self._build_factor_info(selected.head(top_n))
    
    def select_v6_reversal(self, top_n: int = 6) -> List[FactorInfo]:
        """
        v6策略：反转均衡版
        - 动量/反转比例 6:4
        - 只用近期有效的因子
        """
        qualified = self.combined[
            (self.combined['IC_pos_5d'] >= 0.6) &
            (self.combined['abs_IC'] >= 0.01)
        ]
        
        # 分为动量组和反转组
        momentum = qualified[qualified['IC_5d'] > 0].sort_values('IC_5d', ascending=False)
        reversal = qualified[qualified['IC_5d'] < 0].sort_values('IC_5d')
        
        # 选择：动量Top3 + 反转Top2
        mom_selected = momentum.head(4)['factor_id'].tolist()
        rev_selected = reversal.head(2)['factor_id'].tolist()
        selected_fids = mom_selected + rev_selected
        
        selected = self.combined[self.combined['factor_id'].isin(selected_fids)]
        
        return self._build_factor_info(selected.head(top_n))
    
    def _build_factor_info(self, df: pd.DataFrame) -> List[FactorInfo]:
        """构建因子信息列表"""
        factors = []
        for _, row in df.iterrows():
            # 计算近期加权IC
            year_cols = [c for c in df.columns if isinstance(c, int)]
            weighted = 0
            if year_cols:
                weights = {2023: 0.5, 2024: 1.0, 2025: 2.0, 2026: 2.0}
                total_weight = sum(weights.get(y, 0) for y in year_cols)
                if total_weight > 0:
                    weighted = sum(
                        row.get(y, 0) * weights.get(y, 0)
                        for y in year_cols
                    ) / total_weight
            
            factors.append(FactorInfo(
                factor_id=row['factor_id'],
                factor_name=row.get('factor_name', row['factor_id']),
                ic_5d=float(row['IC_5d']),
                ic_pos_5d=float(row['IC_pos_5d']),
                ic_ir=float(row.get('ICIR', 0)),
                ic_cv=float(row.get('ic_cv', 999)),
                weighted_ic=float(weighted),
            ))
        return factors
    
    def get_factors_by_name(self, factors: List[FactorInfo], pattern: str) -> List[str]:
        """按名称模式筛选因子ID"""
        import re
        regex = re.compile(pattern, re.IGNORECASE)
        return [f.factor_id for f in factors if regex.search(f.factor_name)]
