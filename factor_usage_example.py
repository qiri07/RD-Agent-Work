#!/usr/bin/env python3
"""
实际因子使用示例
演示如何在量化策略中使用 RD-Agent 生成的因子
"""

import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

class QuantFactorStrategy:
    """基于RD-Agent因子的量化策略"""
    
    def __init__(self, workspace_path="git_ignore_folder/RD-Agent_workspace"):
        self.workspace_path = Path(workspace_path)
        self.factors = {}
        self.combined_factors = None
        
    def load_factor(self, factor_id):
        """加载单个因子"""
        result_file = self.workspace_path / factor_id / "result.h5"
        if result_file.exists():
            try:
                factor_data = pd.read_hdf(result_file, key='data')
                factor_name = factor_data.columns[0]
                self.factors[factor_name] = factor_data[factor_name]
                print(f"✅ 加载因子: {factor_name}")
                return True
            except Exception as e:
                print(f"❌ 加载因子失败: {e}")
                return False
        return False
    
    def create_multi_factor_strategy(self, factor_ids, strategy_name="综合策略"):
        """创建多因子策略"""
        print(f"\n🎯 创建 {strategy_name}")
        print("-" * 50)
        
        # 加载所有因子
        success_count = 0
        for factor_id in factor_ids:
            if self.load_factor(factor_id):
                success_count += 1
        
        if success_count == 0:
            print("❌ 没有成功加载任何因子")
            return False
            
        # 合并因子
        self.combined_factors = pd.DataFrame(self.factors)
        
        # 处理缺失值
        self.combined_factors = self.combined_factors.fillna(method='ffill').fillna(0)
        
        # 标准化因子
        self.combined_factors = (self.combined_factors - self.combined_factors.mean()) / self.combined_factors.std()
        
        print(f"📊 策略统计:")
        print(f"   - 成功加载因子: {success_count}/{len(factor_ids)}")
        print(f"   - 因子数量: {len(self.factors)}")
        print(f"   - 数据点数: {len(self.combined_factors)}")
        print(f"   - 股票数量: {self.combined_factors.index.get_level_values(1).nunique()}")
        
        return True
    
    def backtest_simple(self, top_k=30, rebalance_days=20):
        """简单回测"""
        print(f"\n📈 简单回测 (Top {top_k}, 每{rebalance_days}天调仓)")
        print("-" * 50)
        
        if self.combined_factors is None:
            print("❌ 请先创建策略")
            return None
        
        # 计算综合得分 (等权重)
        factor_score = self.combined_factors.mean(axis=1)
        
        # 获取所有交易日期
        dates = factor_score.index.get_level_values(0).unique().sort_values()
        
        # 回测结果
        backtest_results = []
        current_positions = {}
        
        for i, date in enumerate(dates[rebalance_days:], start=rebalance_days):
            # 调仓日
            if i % rebalance_days == 0:
                # 当日股票得分
                date_data = factor_score.xs(date, level=0)
                
                # 去除NaN
                date_data = date_data.dropna()
                
                if len(date_data) >= top_k:
                    # 选择得分最高的股票
                    selected_stocks = date_data.nlargest(top_k)
                    current_positions = {stock: 1/top_k for stock in selected_stocks.index}
            
            # 记录当日持仓
            if current_positions:
                try:
                    # 只计算当日有数据的股票
                    available_stocks = [s for s in current_positions.keys() if s in factor_score.xs(date, level=0).index]
                    if available_stocks:
                        avg_score = factor_score.xs(date, level=0).loc[available_stocks].mean()
                    else:
                        avg_score = np.nan
                        
                    backtest_results.append({
                        'date': date,
                        'positions': len(current_positions),
                        'avg_score': avg_score
                    })
                except Exception as e:
                    # 跳过数据缺失的日期
                    continue
        
        # 转换为DataFrame
        if backtest_results:
            result_df = pd.DataFrame(backtest_results)
            result_df.set_index('date', inplace=True)
            
            print("📊 回测结果:")
            print(f"   - 回测期间: {result_df.index.min()} 到 {result_df.index.max()}")
            print(f"   - 交易天数: {len(result_df)}")
            print(f"   - 平均持仓: {result_df['positions'].mean():.1f}")
            print(f"   - 平均得分: {result_df['avg_score'].mean():.4f}")
            
            return result_df
        else:
            print("❌ 回测失败")
            return None
    
    def analyze_factor_performance(self):
        """分析因子表现"""
        print(f"\n🔍 因子表现分析")
        print("-" * 50)
        
        if self.combined_factors is None:
            print("❌ 请先创建策略")
            return
        
        # 计算因子相关性
        correlation = self.combined_factors.corr()
        print("📊 因子相关性矩阵:")
        print(correlation.round(3))
        
        # 因子统计
        print(f"\n📈 因子统计特征:")
        stats = self.combined_factors.describe()
        print(stats)
        
        # 检查因子质量
        print(f"\n🎯 因子质量指标:")
        for col in self.combined_factors.columns:
            factor = self.combined_factors[col]
            nan_ratio = factor.isna().sum() / len(factor) * 100
            outlier_ratio = ((factor > 3) | (factor < -3)).sum() / len(factor) * 100
            
            print(f"   {col}:")
            print(f"     - 缺失率: {nan_ratio:.2f}%")
            print(f"     - 异常值率: {outlier_ratio:.2f}%")
            print(f"     - 标准差: {factor.std():.4f}")

def demo_momentum_strategy():
    """演示动量策略"""
    print("=" * 60)
    print("RD-Agent 因子使用示例: 动量策略")
    print("=" * 60)
    
    strategy = QuantFactorStrategy()
    
    # 选择动量相关的因子
    momentum_factors = [
        "02d7dce95b7f410aa3ba2f8c2ab29b57",  # 10-day Momentum
        "1adcc39c1ecb48e8b734cf649359c4ee",  # Momentum_5d  
        "889763ef5b55432686a1a2fb5d014d9a",  # Momentum_20d
    ]
    
    # 创建策略
    if strategy.create_multi_factor_strategy(momentum_factors, "动量组合策略"):
        
        # 分析因子表现
        strategy.analyze_factor_performance()
        
        # 简单回测
        backtest_result = strategy.backtest_simple(top_k=20, rebalance_days=10)
        
        if backtest_result is not None:
            # 保存结果
            backtest_result.to_csv("momentum_backtest.csv")
            print(f"✅ 回测结果已保存到 momentum_backtest.csv")

def demo_mixed_strategy():
    """演示混合策略"""
    print("\n" + "=" * 60)
    print("RD-Agent 因子使用示例: 混合策略")
    print("=" * 60)
    
    strategy = QuantFactorStrategy()
    
    # 混合不同类型的因子
    mixed_factors = [
        "02d7dce95b7f410aa3ba2f8c2ab29b57",  # 10-day Momentum (动量)
        "04d1651ebc7043c9bd047ca828cc479e",  # volume_spike (成交量)
        "1e3c8739f45b4179bf192e0b7918bfb8",  # intraday_range_pct (波动率)
        "10fc7c3a981a4cb1a4797c14c5ebf436",  # overnight_return (隔夜收益)
    ]
    
    # 创建策略
    if strategy.create_multi_factor_strategy(mixed_factors, "多因子混合策略"):
        
        # 分析因子表现
        strategy.analyze_factor_performance()
        
        # 简单回测
        backtest_result = strategy.backtest_simple(top_k=30, rebalance_days=15)
        
        if backtest_result is not None:
            # 保存结果
            backtest_result.to_csv("mixed_strategy_backtest.csv")
            print(f"✅ 回测结果已保存到 mixed_strategy_backtest.csv")

def save_factor_data():
    """保存因子数据供其他工具使用"""
    print("\n" + "=" * 60)
    print("RD-Agent 因子数据导出")
    print("=" * 60)
    
    # 导出所有可用因子
    workspace = Path("git_ignore_folder/RD-Agent_workspace")
    factor_dirs = [d for d in workspace.iterdir() if d.is_dir()]
    
    all_factors = {}
    for factor_dir in factor_dirs:
        result_file = factor_dir / "result.h5"
        if result_file.exists():
            try:
                factor_data = pd.read_hdf(result_file, key='data')
                factor_name = factor_data.columns[0]
                all_factors[factor_name] = factor_data[factor_name]
            except:
                continue
    
    # 保存所有因子
    if all_factors:
        all_factors_df = pd.DataFrame(all_factors)
        all_factors_df.to_hdf("all_available_factors.h5", key='data', mode='w')
        print(f"✅ 已导出 {len(all_factors)} 个因子到 all_available_factors.h5")
        print(f"   数据点数: {len(all_factors_df)}")
        print(f"   因子列表: {', '.join(all_factors.keys())}")
    else:
        print("❌ 没有找到可导出的因子")

def main():
    """主函数"""
    print("🚀 RD-Agent 因子使用示例\n")
    
    # 1. 动量策略示例
    demo_momentum_strategy()
    
    # 2. 混合策略示例  
    demo_mixed_strategy()
    
    # 3. 导出因子数据
    save_factor_data()
    
    print("\n" + "=" * 60)
    print("示例运行完成！")
    print("=" * 60)
    print("\n💡 提示:")
    print("1. 可以查看生成的CSV文件了解回测结果")
    print("2. 可以使用 all_available_factors.h5 文件进一步分析")
    print("3. 可以修改因子选择和策略参数进行优化")

if __name__ == "__main__":
    main()