#!/usr/bin/env python3
"""
RD-Agent 因子使用分析工具
用于分析和管理 RD-Agent 生成的量化因子
"""

import pandas as pd
import glob
from pathlib import Path
import os
import warnings
warnings.filterwarnings('ignore')

import config as cfg

class FactorAnalyzer:
    def __init__(self, workspace_path=None):
        self.workspace_path = workspace_path or str(cfg.RDAGENT_WORKSPACE)
        self.factors_dir = Path(self.workspace_path)
        
    def get_all_factors(self):
        """获取所有因子信息"""
        factor_files = list(self.factors_dir.glob("*/factor.py"))
        result_files = list(self.factors_dir.glob("*/result.h5"))
        
        factor_info = []
        for factor_file in factor_files:
            factor_dir = factor_file.parent
            result_file = factor_dir / "result.h5"
            
            factor_id = factor_dir.name
            
            # 读取因子代码获取名称
            factor_name = self._extract_factor_name(factor_file)
            
            # 检查结果文件
            has_result = result_file.exists()
            
            # 如果有结果文件，读取基本信息
            factor_stats = None
            if has_result:
                try:
                    result = pd.read_hdf(result_file, key='data')
                    factor_stats = {
                        'data_points': len(result),
                        'start_date': result.index.get_level_values(0).min(),
                        'end_date': result.index.get_level_values(0).max(),
                        'stocks': result.index.get_level_values(1).nunique(),
                        'mean': result.iloc[:, 0].mean(),
                        'std': result.iloc[:, 0].std(),
                        'min': result.iloc[:, 0].min(),
                        'max': result.iloc[:, 0].max(),
                    }
                except Exception as e:
                    print(f"读取结果文件失败 {factor_id}: {e}")
            
            factor_info.append({
                'factor_id': factor_id,
                'factor_name': factor_name,
                'has_result': has_result,
                'stats': factor_stats,
                'factor_file': str(factor_file),
                'result_file': str(result_file) if has_result else None
            })
            
        return factor_info
    
    def _extract_factor_name(self, factor_file):
        """从因子文件中提取因子名称"""
        try:
            with open(factor_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # 尝试匹配函数名或因子名称
                if 'def calculate_' in content:
                    func_name = content.split('def calculate_')[1].split('(')[0]
                    return func_name
                elif 'factor = ' in content or "factor.name = " in content:
                    lines = content.split('\n')
                    for line in lines:
                        if 'factor.name = ' in line:
                            return line.split("'")[1]
                return "Unknown"
        except:
            return "Unknown"
    
    def analyze_factor_quality(self):
        """分析因子质量"""
        factors = self.get_all_factors()
        
        quality_report = []
        for factor in factors:
            if factor['has_result'] and factor['stats']:
                stats = factor['stats']
                
                # 简单质量指标
                quality = {
                    'factor_id': factor['factor_id'],
                    'factor_name': factor['factor_name'],
                    'data_coverage': f"{stats['data_points']} rows",
                    'date_range': f"{stats['start_date']} to {stats['end_date']}",
                    'stock_coverage': stats['stocks'],
                    'statistics': f"mean={stats['mean']:.4f}, std={stats['std']:.4f}",
                    'value_range': f"[{stats['min']:.4f}, {stats['max']:.4f}]"
                }
                quality_report.append(quality)
        
        return quality_report
    
    def load_factor_data(self, factor_id):
        """加载特定因子的数据"""
        result_file = self.factors_dir / factor_id / "result.h5"
        if result_file.exists():
            try:
                data = pd.read_hdf(result_file, key='data')
                return data
            except Exception as e:
                print(f"加载因子数据失败: {e}")
                return None
        return None
    
    def get_factor_code(self, factor_id):
        """获取因子的Python代码"""
        factor_file = self.factors_dir / factor_id / "factor.py"
        if factor_file.exists():
            with open(factor_file, 'r', encoding='utf-8') as f:
                return f.read()
        return None
    
    def summarize_factors(self):
        """总结因子集合"""
        factors = self.get_all_factors()
        
        # 统计信息
        total_factors = len(factors)
        factors_with_results = sum(1 for f in factors if f['has_result'])
        
        # 按类型分类
        factor_categories = {}
        for factor in factors:
            name = factor['factor_name']
            if 'momentum' in name.lower():
                cat = 'Momentum'
            elif 'volume' in name.lower() or 'vol' in name.lower():
                cat = 'Volume'
            elif 'return' in name.lower():
                cat = 'Return'
            elif 'reversal' in name.lower():
                cat = 'Reversal'
            elif 'volatility' in name.lower() or 'std' in name.lower():
                cat = 'Volatility'
            elif 'correlation' in name.lower() or 'corr' in name.lower():
                cat = 'Correlation'
            else:
                cat = 'Other'
            
            factor_categories[cat] = factor_categories.get(cat, 0) + 1
        
        summary = {
            'total_factors': total_factors,
            'factors_with_results': factors_with_results,
            'factors_with_code_only': total_factors - factors_with_results,
            'categories': factor_categories,
            'success_rate': f"{factors_with_results/total_factors*100:.1f}%"
        }
        
        return summary

def main():
    """主函数：生成因子使用分析报告"""
    
    print("=" * 80)
    print("RD-Agent 因子使用分析报告")
    print("=" * 80)
    
    analyzer = FactorAnalyzer()
    
    # 生成总结报告
    print("\n📊 因子集合概览:")
    print("-" * 40)
    summary = analyzer.summarize_factors()
    print(f"总因子数: {summary['total_factors']}")
    print(f"成功计算因子: {summary['factors_with_results']}")
    print(f"仅有代码因子: {summary['factors_with_code_only']}")
    print(f"成功率: {summary['success_rate']}")
    
    print("\n📈 因子类型分布:")
    for cat, count in summary['categories'].items():
        print(f"  {cat}: {count}")
    
    # 详细质量分析
    print("\n🔍 因子质量详细分析:")
    print("-" * 40)
    quality_report = analyzer.analyze_factor_quality()
    
    # 选择前10个因子展示
    for i, factor in enumerate(quality_report[:10], 1):
        print(f"\n{i}. {factor['factor_name']} (ID: {factor['factor_id']})")
        print(f"   数据量: {factor['data_coverage']}")
        print(f"   时间范围: {factor['date_range']}")
        print(f"   股票数量: {factor['stock_coverage']}")
        print(f"   统计特征: {factor['statistics']}")
        print(f"   数值范围: {factor['value_range']}")
    
    # 使用建议
    print("\n💡 因子使用建议:")
    print("-" * 40)
    print("1. **数据加载**:")
    print("   - 使用 `analyzer.load_factor_data(factor_id)` 加载因子数据")
    print("   - 因子数据格式: MultiIndex (datetime, instrument)")
    
    print("\n2. **因子选择**:")
    print("   - 根据因子类型分布选择多样化因子组合")
    print("   - 检查因子统计特征，避免过度相似因子")
    
    print("\n3. **回测验证**:")
    print("   - 使用 Qlib 或回测框架验证因子效果")
    print("   - 建议先在小样本数据上验证，再全量测试")
    
    print("\n4. **因子组合**:")
    print("   - 可以将多个因子结果合并用于多因子模型")
    print("   - 注意处理缺失值和标准化问题")
    
    print("\n5. **持续优化**:")
    print("   - 根据回测结果选择表现最好的因子")
    print("   - 可通过修改 factor.py 文件调整因子逻辑")
    
    # 示例代码
    print("\n🔧 使用示例代码:")
    print("-" * 40)
    print("""
# 初始化分析器
analyzer = FactorAnalyzer()

# 获取所有因子信息
factors = analyzer.get_all_factors()

# 加载特定因子数据
factor_data = analyzer.load_factor_data("02d7dce95b7f410aa3ba2f8c2ab29b57")

# 获取因子代码
factor_code = analyzer.get_factor_code("02d7dce95b7f410aa3ba2f8c2ab29b57")
print(factor_code)

# 分析因子质量
quality_report = analyzer.analyze_factor_quality()
    """)
    
    print("\n" + "=" * 80)
    print("分析完成！")
    print("=" * 80)

if __name__ == "__main__":
    main()