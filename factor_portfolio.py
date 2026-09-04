#!/usr/bin/env python3
"""
因子组合与回测工具
将多个因子组合用于量化回测
"""

import pandas as pd
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

class FactorPortfolio:
    def __init__(self, workspace_path="git_ignore_folder/RD-Agent_workspace"):
        self.workspace_path = workspace_path
        self.factors_dir = Path(workspace_path)
        
    def load_multiple_factors(self, factor_ids, normalize=True):
        """
        加载多个因子数据
        
        参数:
            factor_ids: 因子ID列表
            normalize: 是否标准化
            
        返回:
            合并的因子DataFrame
        """
        all_factors = {}
        
        for factor_id in factor_ids:
            result_file = self.factors_dir / factor_id / "result.h5"
            if result_file.exists():
                try:
                    factor_data = pd.read_hdf(result_file, key='data')
                    factor_name = factor_data.columns[0]
                    all_factors[factor_name] = factor_data[factor_name]
                    print(f"✅ 加载因子: {factor_name}")
                except Exception as e:
                    print(f"❌ 加载因子失败 {factor_id}: {e}")
            else:
                print(f"⚠️  因子文件不存在: {factor_id}")
        
        if not all_factors:
            print("没有成功加载任何因子")
            return None
            
        # 合并因子
        combined_factors = pd.concat(all_factors, axis=1)
        
        # 标准化处理
        if normalize:
            combined_factors = self._normalize_factors(combined_factors)
            
        return combined_factors
    
    def _normalize_factors(self, factor_df):
        """标准化因子"""
        normalized = factor_df.copy()
        
        for col in normalized.columns:
            # Z-score 标准化
            mean = normalized[col].mean()
            std = normalized[col].std()
            if std > 0:
                normalized[col] = (normalized[col] - mean) / std
            else:
                normalized[col] = 0
                
        return normalized
    
    def calculate_factor_score(self, factor_df, weights=None):
        """
        计算综合因子得分
        
        参数:
            factor_df: 因子DataFrame
            weights: 权重字典，如果为None则等权重
            
        返回:
            综合得分Series
        """
        if weights is None:
            # 等权重
            weights = {col: 1/len(factor_df.columns) for col in factor_df.columns}
        else:
            # 归一化权重
            total_weight = sum(weights.values())
            weights = {k: v/total_weight for k, v in weights.items()}
        
        # 计算加权得分
        score = pd.Series(0, index=factor_df.index)
        
        for factor_name, weight in weights.items():
            if factor_name in factor_df.columns:
                score += factor_df[factor_name] * weight
            else:
                print(f"⚠️  因子 {factor_name} 不在数据中")
        
        return score
    
    def backtest_factor(self, factor_data, top_k=50, rebalance_freq='M'):
        """
        简单的因子回测
        
        参数:
            factor_data: 因子数据
            top_k: 选股数量
            rebalance_freq: 再平衡频率 (D=日, W=周, M=月)
            
        返回:
            回测结果
        """
        print(f"\n📊 因子回测分析 (Top {top_k})")
        print("=" * 40)
        
        # 按日期分组
        results = {}
        
        for date, group in factor_data.groupby(level=0):
            # 去除NaN
            group = group.dropna()
            
            if len(group) < top_k:
                continue
                
            # 选择因子值最大的股票
            top_stocks = group.nlargest(top_k, group.columns[0])
            
            # 计算下一期收益 (简化版)
            results[date] = {
                'selected_stocks': len(top_stocks),
                'factor_mean': top_stocks.iloc[:, 0].mean(),
                'factor_std': top_stocks.iloc[:, 0].std()
            }
        
        if results:
            results_df = pd.DataFrame.from_dict(results, orient='index')
            return results_df
        else:
            return None

def main():
    """演示因子组合使用"""
    print("=" * 80)
    print("RD-Agent 因子组合与回测工具")
    print("=" * 80)
    
    portfolio = FactorPortfolio()
    
    # 1. 选择几个表现较好的因子进行组合
    selected_factors = [
        "02d7dce95b7f410aa3ba2f8c2ab29b57",  # 10-day Momentum
        "04d1651ebc7043c9bd047ca828cc479e",  # volume_spike
        "1adcc39c1ecb48e8b734cf649359c4ee",  # Momentum_5d
        "1e3c8739f45b4179bf192e0b7918bfb8",  # intraday_range_pct
        "f834f42beedd44bfa9238a8501b21b5c"   # short_term_reversal_5d
    ]
    
    print("\n🔧 步骤1: 加载多个因子")
    print("-" * 40)
    combined_factors = portfolio.load_multiple_factors(selected_factors)
    
    if combined_factors is None:
        print("❌ 无法加载因子数据")
        return
        
    print(f"\n📈 因子组合统计:")
    print(f"   - 因子数量: {len(combined_factors.columns)}")
    
    # 获取时间范围，处理可能的混合类型
    try:
        dates = combined_factors.index.get_level_values(0)
        # 转换为pandas datetime
        if hasattr(dates, 'to_datetime'):
            dates = pd.to_datetime(dates)
        
        if len(dates) > 0:
            min_date = dates.min()
            max_date = dates.max()
            print(f"   - 数据时间范围: {min_date} 到 {max_date}")
    except Exception as e:
        print(f"   - 时间范围获取失败: {e}")
    
    print(f"   - 股票数量: {combined_factors.index.get_level_values(1).nunique()}")
    print(f"   - 总数据点: {len(combined_factors)}")
    
    # 2. 计算综合因子得分
    print("\n🎯 步骤2: 计算综合因子得分")
    print("-" * 40)
    
    # 可以自定义权重
    custom_weights = {
        '10-day Momentum': 0.3,
        'volume_spike': 0.2,
        'Momentum_5d': 0.2,
        'intraday_range_pct': 0.15,
        'short_term_reversal_5d': 0.15
    }
    
    factor_score = portfolio.calculate_factor_score(combined_factors, weights=custom_weights)
    
    print(f"   - 得分均值: {factor_score.mean():.4f}")
    print(f"   - 得分标准差: {factor_score.std():.4f}")
    print(f"   - 得分范围: [{factor_score.min():.4f}, {factor_score.max():.4f}]")
    
    # 3. 简单回测分析
    print("\n📊 步骤3: 因子回测分析")
    print("-" * 40)
    
    # 准备回测数据 (使用综合得分)
    score_df = factor_score.to_frame('combined_score')
    backtest_result = portfolio.backtest_factor(score_df, top_k=50)
    
    if backtest_result is not None:
        print("   回测期间因子表现:")
        print(backtest_result.describe())
    
    # 4. 保存组合因子
    print("\n💾 步骤4: 保存组合因子")
    print("-" * 40)
    
    output_path = Path("combined_factors.h5")
    combined_factors.to_hdf(output_path, key='data', mode='w')
    print(f"   ✅ 组合因子已保存到: {output_path}")
    
    # 5. 导出因子用于其他分析
    output_score_path = Path("factor_score.h5")
    factor_score.to_hdf(output_score_path, key='data', mode='w')
    print(f"   ✅ 因子得分已保存到: {output_score_path}")
    
    print("\n💡 使用建议:")
    print("-" * 40)
    print("1. 可以将生成的组合因子导入到 Qlib 中进行正式回测")
    print("2. 可以调整权重，观察不同因子组合的效果")
    print("3. 建议增加风险控制措施，如最大回撤控制")
    print("4. 可以使用更多因子进行组合，提高策略稳定性")
    
    # 6. 查看因子相关性
    print("\n🔍 因子相关性分析:")
    print("-" * 40)
    correlation_matrix = combined_factors.corr()
    print(correlation_matrix)
    
    print("\n" + "=" * 80)
    print("因子组合分析完成！")
    print("=" * 80)

if __name__ == "__main__":
    main()