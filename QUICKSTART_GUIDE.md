# RD-Agent 因子快速入门指南

## 🚀 5分钟快速开始

### 1. 查看因子概况
```bash
source rdagent-env/bin/activate
python3 analyze_factors.py
```
这会显示：
- 总共66个因子，52个成功计算
- 按类型分类的统计信息
- 前10个因子的详细特征

### 2. 尝试因子组合
```bash
python3 factor_portfolio.py
```
这会：
- 加载5个精选因子
- 计算因子相关性
- 生成组合因子数据
- 进行简单回测分析

### 3. 运行完整示例
```bash
python3 factor_usage_example.py
```
这会演示：
- 动量策略构建
- 混合策略构建
- 因子数据导出

## 📊 当前因子状态

**工作流状态**:
- 总结果数: 52 (result.h5)  
- 因子实现: 66 (factor.py)
- 本次新增: +43
- 成功率: 78.8%

**因子分类**:
- Momentum: 24个 (36.4%)
- Volume: 18个 (27.3%)
- Return: 10个 (15.1%)
- Reversal: 3个 (4.5%)
- Other: 11个 (16.7%)

## 💡 三种使用方式

### 方式一: 使用预设工具 (推荐新手)

**因子分析**:
```bash
python3 analyze_factors.py
```

**因子组合**:
```bash
python3 factor_portfolio.py
```

**完整示例**:
```bash
python3 factor_usage_example.py
```

### 方式二: 编程接口使用

```python
import pandas as pd
from pathlib import Path

# 加载单个因子
factor_id = "02d7dce95b7f410aa3ba2f8c2ab29b57"
result_file = Path(f"git_ignore_folder/RD-Agent_workspace/{factor_id}/result.h5")
factor_data = pd.read_hdf(result_file, key='data')

print(f"因子名称: {factor_data.columns[0]}")
print(f"数据形状: {factor_data.shape}")
print(f"统计信息:\n{factor_data.describe()}")
```

### 方式三: 使用导出的综合数据

```python
import pandas as pd

# 加载所有可用因子
all_factors = pd.read_hdf('all_available_factors.h5', key='data')
print(f"可用因子: {all_factors.columns.tolist()}")
print(f"数据点数: {len(all_factors)}")

# 选择几个因子使用
selected_factors = all_factors[['10-day Momentum', 'volume_spike', 'Momentum_5d']]
```

## 🎯 快速策略示例

### 简单动量策略
```python
from factor_portfolio import FactorPortfolio

portfolio = FactorPortfolio()

# 选择动量因子
momentum_factors = [
    "02d7dce95b7f410aa3ba2f8c2ab29b57",  # 10-day Momentum
    "1adcc39c1ecb48e8b734cf649359c4ee",  # Momentum_5d
    "889763ef5b55432686a1a2fb5d014d9a"   # Momentum_20d
]

# 创建策略
combined = portfolio.load_multiple_factors(momentum_factors)

# 计算得分 (等权重)
factor_score = portfolio.calculate_factor_score(combined)

print(f"策略得分统计:")
print(factor_score.describe())
```

## 📁 生成的文件说明

### 数据文件
- `all_available_factors.h5` - 42个因子，399,282数据点
- `combined_factors.h5` - 5个精选因子组合
- `factor_score.h5` - 因子综合得分
- `momentum_backtest.csv` - 动量策略回测结果
- `mixed_strategy_backtest.csv` - 混合策略回测结果

### 工具脚本
- `analyze_factors.py` - 因子分析工具 (9.1KB)
- `factor_portfolio.py` - 因子组合工具 (8.1KB)  
- `factor_usage_example.py` - 使用示例 (9.9KB)

### 文档
- `FACTOR_USAGE_GUIDE.md` - 详细使用指南
- `FACTOR_WORKFLOW_ANALYSIS.md` - 工作流分析报告
- `RDAGENT_STATUS.md` - 系统状态报告

## 🔍 快速查询命令

```bash
# 查看因子数量
find git_ignore_folder/RD-Agent_workspace -name "factor.py" | wc -l

# 查看成功计算的因子数量
find git_ignore_folder/RD-Agent_workspace -name "result.h5" | wc -l

# 查看最新日志
ls -lt log/ | head -5

# 查看生成的数据文件
ls -lh *.h5 *.csv
```

## 💡 常见问题速解

**Q: 如何知道哪些因子表现好？**
A: 运行 `analyze_factors.py` 查看因子统计特征，优先选择标准差适中、缺失值少的因子。

**Q: 如何选择因子进行组合？**
A: 从不同类型因子中各选1-2个，避免选择相关性过高的因子 (相关系数>0.9)。

**Q: 因子数据如何更新？**
A: 重新运行 RD-Agent 工作流，或手动修改对应因子目录中的 factor.py 文件。

**Q: 如何进行正式回测？**
A: 可以将生成的因子数据导入 Qlib 等专业回测平台，或使用 `factor_portfolio.py` 中的简单回测功能。

## 🎓 学习路径建议

### 初学者
1. 运行 `analyze_factors.py` 了解因子概况
2. 运行 `factor_usage_example.py` 看完整示例
3. 查看 `FACTOR_USAGE_GUIDE.md` 学习详细用法

### 中级用户  
1. 修改 `factor_usage_example.py` 中的因子选择
2. 调整策略参数 (选股数量、调仓频率)
3. 分析不同因子组合的表现

### 高级用户
1. 自定义因子计算逻辑
2. 集成到现有量化系统
3. 进行深入的因子研究和优化

## 🚀 下一步

1. **立即尝试**: 运行 `python3 factor_usage_example.py` 看实际效果
2. **深入学习**: 阅读 `FACTOR_USAGE_GUIDE.md` 了解所有功能
3. **动手实践**: 修改示例代码，尝试自己的因子组合

---

**快速开始**: `python3 factor_usage_example.py`  
**详细文档**: `FACTOR_USAGE_GUIDE.md`  
**工作流分析**: `FACTOR_WORKFLOW_ANALYSIS.md`