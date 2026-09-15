# 因子计算数据泄露检查报告

**检查时间**: 2026-09-12  
**检查范围**: `engine/factor.py` 及 66 个 workspace 因子文件

---

## 一、代码层面：✅ 无未来数据泄露

### 静态扫描结果

| 检查项 | 结果 |
|--------|------|
| `shift(-n)` 负移位模式 | **未检出** ✅ |
| `pct_change().shift(-n)` | 仅用于 forward return 计算，**正确** ✅ |
| 横截面 Z-score 标准化 | 仅用当日截面数据，**正确** ✅ |
| 回测执行时序 | T日信号 → T+1日开盘买入，**正确** ✅ |

### 关键因子代码验证

**PriceMomentum_5d** (IC报告最高因子):
```python
close_lag4 = close.shift(4)           # ✅ 使用过去4天数据
PriceMomentum_5d = close / close_lag4 - 1  # ✅ 正确的动量计算
```

**forward return 计算** (`engine/ic_scan.py:98`):
```python
fwd_return = returns_df.groupby("instrument")["$close"].pct_change(fd).shift(-fd)
# ✅ 标准做法：将 t 到 t+N 的收益分配回 t 日
```

---

## 二、发现的关键问题：❌ 数据源不一致

### 索引匹配问题

```
factor 索引: ['datetime', 'instrument']  (976 个交易日)
returns 索引: ['date', 'instrument']     (1619 个交易日)
共同日期: 976 天
仅 returns 有: 643 天 (2020-01-02 ~ 2022-08-30)
```

### Session vs Source 数据对比

| 数据源 | 行数 | 日期范围 | 股票数 |
|--------|------|----------|--------|
| **Source** (`daily_pv_full.parquet`) | 7,450,332 | 2020-01-02 ~ 2026-09-12 | 5,240 |
| **Session** (`daily_pv.parquet`) | 4,310,988 | 2022-08-31 ~ 2026-09-09 | 5,552 |

**差异详情**:
- Session 缺少 649 个交易日的历史数据
- Session 多出 326 只 Source 中没有的股票
- **相同日期的价格数据不一致**（可能是不同来源/复权方式）

---

## 三、IC 计算错误验证

以 PriceMomentum_5d 为例：

| 指标 | 流水线报告值 | 重新计算的正确值 |
|------|-------------|-----------------|
| IC_5d | **+0.5327** | **-0.0400** |
| IC > 0 比例 | 100% | 38.9% |
| 年度 IC (2023) | +0.52 | -0.056 |
| t-statistic | 437.7 | N/A（无效）|

```
✅ 正确 IC: -0.04（动量因子在A股短期反转，符合常识）
❌ 报告 IC: +0.53（数据不匹配导致的虚假高IC）
```

**根因**: IC 计算使用 session 的预计算因子结果（旧数据），但 forward return 从 source 全量数据计算（新数据），导致时空不匹配。

---

## 四、回测表现分析

| 指标 | 数值 |
|------|------|
| 总收益率 | **-90.29%** |
| 胜率 | 38.7% |
| 平均持仓周期 | 249.8 天（目标5天）|
| 总交易次数 | 10,356 |

回测表现差的原因**不是数据泄露**，而是：
1. IC 虚高导致选择了无效因子
2. 数据不一致导致选股逻辑失真

---

## 五、修复建议

### 1. 重新同步 Session 数据
```bash
python3 batch_recompute_factors.py --phase1
```

### 2. 修复 IC 计算逻辑
在 `engine/ic_scan.py` 中，应使用 session 自身的价格数据计算 forward return：

```python
# 当前错误：使用 source 全量数据
src_pq = cfg.DAILY_PV_PQ  # 全量数据
fpq = pd.read_parquet(src_pq)
fpq_reset["return_5d"] = fpq_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)

# 建议改为：使用 session 数据
# 每个 session 已有自己的 daily_pv.parquet，应使用其中的数据
```

### 3. 添加数据一致性检查
在 IC 计算前验证因子数据与价格数据的时间范围和股票列表是否一致。

---

## 六、总结

| 检查项 | 结论 |
|--------|------|
| 因子代码未来数据泄露 | **无** ✅ |
| IC 计算逻辑正确性 | **代码正确，但数据输入不一致** ⚠️ |
| 回测执行时序 | **正确** ✅ |
| 数据源一致性 | **存在严重问题** ❌ |

**核心问题**: Session 数据是旧版本快照，与当前 source 数据不一致，导致 IC 虚高和回测结果不可信。

**建议**: 重新运行完整的因子重算和 IC 分析流程，确保数据一致性。
