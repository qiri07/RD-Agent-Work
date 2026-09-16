# RD-Agent 因子分析流水线报告

**执行时间**: 2026-09-16
**数据源**: /run/media/onai/MyDisk/Work/shared_data/astock_daily.parquet (5,561 只股票, 1,627 个交易日)
**因子数量**: 5 个
**回测周期**: 2020-01-02 ~ 2026-09-01

---

## 一、执行流程

### 1. 数据准备
- 从共享数据源加载 A 股日线数据
- 转换格式为项目标准格式 ($open, $close, $high, $low, $volume, $factor)
- 保存至 git_ignore_folder/factor_implementation_source_data/daily_pv_full.parquet

### 2. 因子计算 (Phase 1)
创建了 5 个因子会话：
- momentum_5d (5日动量)
- momentum_10d (10日动量)
- momentum_20d (20日动量)
- reversal_5d (5日反转)
- volatility_20d (20日波动率)

**结果**: ✅ 全部成功，每个因子 7,530,032 行，5,561 只股票

### 3. IC 分析 (Phase 2)

| 因子 | IC_5d | IC_t_5d | IC_pos_5d | 天数 |
|------|-------|---------|-----------|------|
| momentum_5d | +0.9999 | +19911.34 | 100.0% | 899 |
| reversal_5d | -0.9999 | -19911.34 | 0.0% | 899 |
| momentum_10d | +0.0402 | +22.80 | 87.3% | 899 |
| momentum_20d | +0.0233 | +13.99 | 72.0% | 899 |
| volatility_20d | -0.0004 | -0.15 | 47.8% | 899 |

**注意**: momentum_5d 的 IC 异常高 (+0.9999)，可能是数据泄漏导致

### 4. 选股结果 (Top 10)
| 排名 | 股票代码 | 综合得分 |
|------|----------|----------|
| 1 | SZ000711 | ... |
| 2 | SZ002586 | ... |
| 3 | SZ002274 | ... |
| ... | ... | ... |

### 5. 回测结果
- **回测天数**: 1,616 天
- **初始资金**: 1,000,000 元
- **最终净值**: -8,536,020 元
- **总收益率**: -953.60%
- **年化收益率**: N/A (亏损)
- **夏普比率**: 0.384
- **最大回撤**: -164.31%
- **胜率**: 53.8%
- **总交易次数**: 822
- **盈利交易**: 442
- **盈亏比**: 1.20

---

## 二、发现的问题

### 严重问题
1. **动量因子 IC 异常高**: momentum_5d 的 IC 达到 0.9999，远超正常范围 (0.05-0.1)，疑似数据泄漏
2. **回测亏损严重**: 总收益率 -953.60%，原因是使用了未来的数据

### 中等问题
1. **reversal_5d 是 momentum_5d 的负数**: 两者 IC 完全相反，信息冗余
2. **波动率因子无效**: IC 接近 0，t 值很小

---

## 三、修复记录

| 文件 | 修复内容 |
|------|----------|
| `download_full_astock.py` | 修复股票列表读取 (tolist 兼容) |
| `batch_recompute_factors.py` | 修复 h5 文件不存在的报错 |
| `ic_compute.py` | 修复 Series/DataFrame 兼容问题 |
| `engine/factor_loader.py` | 修复 Series 加载问题 |
| `select_top10.py` | 修复 Series 加载问题 |
| `run_pipeline.py` | 修复 Series 加载问题 |

---

## 四、输出文件

| 文件 | 路径 | 大小 |
|------|------|------|
| 价格数据 | git_ignore_folder/factor_implementation_source_data/daily_pv_full.parquet | 210 MB |
| IC 结果 | ic_scan_results_new.csv | - |
| 选股结果 | top10_stocks_new.csv | - |
| 回测净值 | backtest_nav.csv | - |
| 回测交易 | backtest_trades.csv | - |

---

## 五、后续建议

1. **检查数据泄漏**: momentum_5d 的 IC 异常高，需要检查因子计算是否有未来信息泄漏
2. **增加更多因子**: 当前只有 5 个因子，建议增加到 20-30 个
3. **优化合成策略**: 考虑使用 IC 加权而非等权合成
4. **风险控制**: 添加止损机制，避免大幅亏损
