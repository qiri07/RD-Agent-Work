# RD-Agent 因子使用指南

## 📊 当前状态

根据最新的工作流状态统计：

| 指标 | 数值 |
|------|------|
| 总结果数 | 52 (result.h5 文件) |
| 因子实现 | 66 (factor.py 文件) |
| 本次新增 | +43 个因子 |
| 成功率 | 78.8% (52/66) |

## 🔍 因子类型分布

生成的因子主要分为以下几类：

- **Momentum (动量)**: 24 个因子
- **Volume (成交量)**: 18 个因子  
- **Return (收益率)**: 10 个因子
- **Reversal (反转)**: 3 个因子
- **Other (其他)**: 11 个因子

## 📁 文件结构

```
git_ignore_folder/RD-Agent_workspace/
├── [因子ID目录]/
│   ├── factor.py           # 因子实现代码
│   ├── result.h5           # 因子计算结果
│   ├── daily_pv.h5         # 原始数据
│   └── README.md           # 说明文件
```

## 🚀 快速开始

### 1. 使用分析工具

系统提供了两个核心工具来使用这些因子：

#### 因子分析工具 (`analyze_factors.py`)
```bash
source rdagent-env/bin/activate
python3 analyze_factors.py
```

**功能**:
- 分析所有因子的基本统计特征
- 按类型分类因子
- 提供因子质量评估
- 生成使用建议

#### 因子组合工具 (`factor_portfolio.py`)  
```bash
source rdagent-env/bin/activate
python3 factor_portfolio.py
```

**功能**:
- 加载多个因子进行组合
- 计算因子相关性
- 生成综合因子得分
- 简单的回测分析

### 2. 编程接口使用

#### 加载单个因子
```python
import pandas as pd
from pathlib import Path

# 加载因子数据
factor_id = "02d7dce95b7f410aa3ba2f8c2ab29b57"
result_file = Path(f"git_ignore_folder/RD-Agent_workspace/{factor_id}/result.h5")
factor_data = pd.read_hdf(result_file, key='data')

print(factor_data.head())
print(f"因子统计: {factor_data.describe()}")
```

#### 加载多个因子
```python
# 使用组合工具
from factor_portfolio import FactorPortfolio

portfolio = FactorPortfolio()

# 选择因子ID
factor_ids = [
    "02d7dce95b7f410aa3ba2f8c2ab29b57",  # 10-day Momentum
    "04d1651ebc7043c9bd047ca828cc479e",  # volume_spike
    "1adcc39c1ecb48e8b734cf649359c4ee"   # Momentum_5d
]

# 加载并合并因子
combined_factors = portfolio.load_multiple_factors(factor_ids)
```

#### 查看因子代码
```python
# 查看因子实现代码
factor_file = Path(f"git_ignore_folder/RD-Agent_workspace/{factor_id}/factor.py")
with open(factor_file, 'r') as f:
    print(f.read())
```

## 🎯 因子应用策略

### 1. 因子选择建议

**多元化组合**:
- 选择不同类型的因子进行组合
- 动量因子 + 成交量因子 + 反转因子
- 避免选择高度相关的因子

**质量筛选**:
- 检查因子的数据完整性 (避免过多NaN值)
- 分析因子统计特征 (均值、标准差、极值)
- 确保因子在不同市场环境下表现稳定

### 2. 因子组合方法

#### 等权重组合
```python
from factor_portfolio import FactorPortfolio

portfolio = FactorPortfolio()
combined_factors = portfolio.load_multiple_factors(factor_ids)
equal_weights = None  # 默认等权重
factor_score = portfolio.calculate_factor_score(combined_factors, equal_weights)
```

#### 自定义权重组合
```python
# 根据因子表现设置权重
custom_weights = {
    '10-day Momentum': 0.4,
    'volume_spike': 0.3, 
    'Momentum_5d': 0.3
}

factor_score = portfolio.calculate_factor_score(combined_factors, custom_weights)
```

### 3. 回测验证

#### 使用组合工具的简单回测
```python
# 准备因子得分
score_df = factor_score.to_frame('combined_score')

# 简单回测分析
backtest_result = portfolio.backtest_factor(score_df, top_k=50)
```

#### 导出因子到 Qlib
```python
# 保存因子数据
combined_factors.to_hdf('combined_factors.h5', key='data', mode='w')

# 在 Qlib 配置中使用
# conf_combined_factors.yaml
# config: "combined_factors_df.parquet"
```

## 📈 高级应用

### 1. 因子筛选与优化

```python
# 分析因子相关性
correlation_matrix = combined_factors.corr()

# 移除高相关因子
threshold = 0.9  # 相关系数阈值
to_remove = set()
for i in range(len(correlation_matrix.columns)):
    for j in range(i+1, len(correlation_matrix.columns)):
        if abs(correlation_matrix.iloc[i,j]) > threshold:
            to_remove.add(correlation_matrix.columns[j])

filtered_factors = combined_factors.drop(columns=list(to_remove))
```

### 2. 动态因子选择

```python
# 根据时间段选择表现好的因子
def select_factors_by_period(factor_data, start_date, end_date):
    period_data = factor_data.loc[(factor_data.index.get_level_values(0) >= start_date) & 
                                  (factor_data.index.get_level_values(0) <= end_date)]
    
    # 计算每个因子的IC/IR指标
    factor_performance = {}
    for col in period_data.columns:
        # 简化的IC计算
        ic = period_data[col].corr(period_data['next_return'])
        ir = ic / period_data[col].std()
        factor_performance[col] = {'IC': ic, 'IR': ir}
    
    return factor_performance
```

### 3. 风险控制

```python
# 添加风险因子到组合
risk_factors = [
    "market_risk_factor_id",  # 市场风险因子
    "sector_risk_factor_id",  # 行业风险因子
]

combined_with_risk = portfolio.load_multiple_factors(factor_ids + risk_factors)

# 计算风险调整后的因子得分
risk_adjusted_score = portfolio.calculate_factor_score(combined_with_risk)
```

## 💡 使用建议

### 最佳实践

1. **数据质量检查**:
   - 检查因子数据的完整性
   - 处理异常值和缺失值
   - 确保时间序列的一致性

2. **因子稳定性**:
   - 进行样本外测试
   - 避免过度拟合
   - 定期更新因子

3. **风险管理**:
   - 设置最大持仓比例
   - 添加止损机制
   - 考虑市场环境变化

### 常见问题

**Q: 如何选择最佳的因子组合？**
A: 建议从不同类型因子中选择1-2个表现稳定的因子，通过回测试验不同组合的效果。

**Q: 因子数据如何更新？**
A: 重新运行 RD-Agent 工作流，或手动更新因子代码中的数据源。

**Q: 如何评估因子表现？**
A: 可以使用 IC/IR 指标、夏普比率、最大回撤等量化指标进行评估。

## 🔧 技术支持

### 文件路径
- 工作空间: `git_ignore_folder/RD-Agent_workspace/`
- 日志文件: `log/2026-09-02_06-08-29-928566/`
- 工具脚本: `analyze_factors.py`, `factor_portfolio.py`

### 命令参考
```bash
# 运行因子分析
python3 analyze_factors.py

# 运行因子组合
python3 factor_portfolio.py

# 查看工作流状态
find log -name "*.pkl" | grep feedback

# 统计因子数量
find git_ignore_folder/RD-Agent_workspace -name "factor.py" | wc -l
```

## 📞 获取帮助

如遇到问题，请：
1. 检查 `RDAGENT_STATUS.md` 了解系统状态
2. 查看日志文件了解详细错误信息
3. 参考因子实现代码理解因子逻辑

---

**更新时间**: 2026-09-02  
**工作流版本**: RD-Agent v0.8.0  
**数据范围**: 2018-01-02 ~ 2026-08-31 (483只A股)