# RD-Agent 因子使用指南

## 📊 当前状态

| 指标 | 数值 |
|------|------|
| 总结果数 | 52 (result.h5 文件) |
| 因子实现 | 66 (factor.py 文件) |
| 本次新增 | +43 个因子 |
| 成功率 | 78.8% (52/66) |
| 有效 IC 交易日 | 967 天（每日 ≥50 只股票） |
| 最强因子 | Momentum_5d 变体（IC_5d = 0.0717） |
| 数据范围 | 2018-01-02 ~ 2026-08-31（~5,553 只 A股） |

## 🔍 因子类型分布

生成的因子主要分为以下几类：

- **Momentum (动量)**: 24 个因子
- **Volume (成交量)**: 18 个因子
- **Return (收益率)**: 10 个因子
- **Reversal (反转)**: 3 个因子
- **Other (其他)**: 11 个因子

## 🚀 快速开始

### 一键流程（推荐）

```bash
source rdagent-env/bin/activate
python run_pipeline.py              # IC分析 → 选股 → 飞书推送
python run_pipeline.py --ic-only    # 只跑 IC 分析
python run_pipeline.py --stocks-only  # 只选股（用已有 IC 结果）
```

### 单独运行各模块

```bash
# IC 因子分析
python run_ic_fast.py

# 全量因子选股
python full_factor_stock_selection.py

# 回测 Top-10 策略
python backtest_top10.py

# 飞书推送（CLI 模式）
python feishu_notify.py \
  --ic-results ic_scan_results_new.csv \
  --stocks top10_stocks_new.csv
```

### 配置管理

所有参数统一在 `config.py` 中管理，支持环境变量覆盖：

```bash
export BACKTEST_TOP_K=20
export BACKTEST_HOLD_DAYS=10
export FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
```

## 📁 文件结构

```
RD-Agent-Work/
├── config.py                    # 统一配置管理
├── feishu_notify.py             # 飞书推送模块
├── run_pipeline.py              # 一体化流水线
├── run_ic_fast.py               # 高性能 IC 分析
├── full_factor_stock_selection.py  # 全量因子选股
├── backtest_top10.py            # 回测引擎
├── factor_scan_mem_optimized.py # 内存优化版扫描
├── analyze_factors.py           # 因子分析工具
├── factor_portfolio.py          # 多因子组合工具
├── visualize_results.py         # 可视化
├── tests/                       # 单元测试（25 tests）
└── git_ignore_folder/           # 数据文件（不入库）
    ├── RD-Agent_workspace/      # 66 因子会话
    └── factor_implementation_source_data/
        ├── daily_pv_full.parquet  # 价格数据
        └── ic_scan_results_new.parquet
```

## 🔧 编程接口

### 加载单个因子

```python
import pandas as pd
from pathlib import Path
import config as cfg

factor_id = "02d7dce95b7f410aa3ba2f8c2ab29b57"
result_file = cfg.RDAGENT_WORKSPACE / factor_id / "result.h5"
factor_data = pd.read_hdf(result_file, key='data')

print(factor_data.head())
print(f"因子统计: {factor_data.describe()}")
```

### 加载多个因子并组合

```python
from factor_portfolio import FactorPortfolio

portfolio = FactorPortfolio()
factor_ids = [
    "02d7dce95b7f410aa3ba2f8c2ab29b57",  # 10-day Momentum
    "04d1651ebc7043c9bd047ca828cc479e",  # volume_spike
    "1adcc39c1ecb48e8b734cf649359c4ee",   # Momentum_5d
]
combined_factors = portfolio.load_multiple_factors(factor_ids)
```

### 因子分析

```python
from analyze_factors import FactorAnalyzer

analyzer = FactorAnalyzer()
summary = analyzer.summarize_factors()
print(f"总因子数: {summary['total_factors']}")
print(f"因子类型分布: {summary['categories']}")
```

### 查看因子代码

```python
factor_file = cfg.RDAGENT_WORKSPACE / "02d7dce95b7f410aa3ba2f8c2ab29b57" / "factor.py"
with open(factor_file, 'r') as f:
    print(f.read())
```

## 🎯 因子应用策略

### 因子选择建议

**多元化组合**:
- 选择不同类型的因子进行组合
- 动量因子 + 成交量因子 + 反转因子
- 避免选择高度相关的因子

**质量筛选**:
- 检查因子的数据完整性（避免过多 NaN 值）
- 分析因子统计特征（均值、标准差、极值）
- 确保因子在不同市场环境下表现稳定

### 多因子组合方法

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
custom_weights = {
    '10-day Momentum': 0.4,
    'volume_spike': 0.3,
    'Momentum_5d': 0.3
}
factor_score = portfolio.calculate_factor_score(combined_factors, custom_weights)
```

### 因子筛选与优化

```python
# 分析因子相关性
correlation_matrix = combined_factors.corr()

# 移除高相关因子（阈值 0.9）
threshold = 0.9
to_remove = set()
for i in range(len(correlation_matrix.columns)):
    for j in range(i+1, len(correlation_matrix.columns)):
        if abs(correlation_matrix.iloc[i, j]) > threshold:
            to_remove.add(correlation_matrix.columns[j])

filtered_factors = combined_factors.drop(columns=list(to_remove))
```

## 💡 使用建议

### 最佳实践

1. **数据质量检查**: 检查因子数据的完整性，处理异常值和缺失值
2. **因子稳定性**: 进行样本外测试，避免过度拟合
3. **风险管理**: 设置最大持仓比例，加入行业中性约束

### 常见问题

**Q: 如何选择最佳的因子组合？**
A: 建议从不同类型因子中选择 1-2 个表现稳定的因子，通过回测试验不同组合的效果。

**Q: 因子数据如何更新？**
A: 重新运行 RD-Agent 工作流，或手动更新因子代码中的数据源。

**Q: 如何评估因子表现？**
A: 使用 IC/IR 指标、夏普比率、最大回撤等量化指标进行评估。

## 🧪 单元测试

```bash
source rdagent-env/bin/activate
python tests/test_config.py        # 9 tests — 配置、环境变量覆盖
python tests/test_feishu_notify.py # 7 tests — 飞书消息格式
python tests/test_ic_computation.py# 9 tests — IC 计算逻辑
# 共 25 tests，全部通过
```

## 📞 获取帮助

如遇到问题，请：
1. 检查 `RDAGENT_STATUS.md` 了解系统状态
2. 查看日志文件了解详细错误信息
3. 参考因子实现代码理解因子逻辑

---

**更新时间**: 2026-09-04  
**工作流版本**: RD-Agent v0.8.0  
**数据范围**: 2018-01-02 ~ 2026-08-31（~5,553 只 A股）
