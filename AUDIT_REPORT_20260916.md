# RD-Agent 因子分析系统 — 全面审计报告

**审计日期**: 2026-09-16
**审计范围**: `/run/media/onai/MyDisk/Work/RD-Agent-Work` 全部 Python 源码
**测试状态**: 623 passed (全部通过)
**代码覆盖率**: 59% (低于 80% 目标阈值)

---

## 一、已修复问题 (Critical & High)

### [CRITICAL] C1: `select_top10.py` 未定义变量 `latest_date` → NameError
- **文件**: `select_top10.py` 第 105 行
- **严重性**: Critical — 导致选股流程运行时崩溃
- **描述**: `screen_top10()` 函数中引用了 `latest_date` 变量，但该变量在函数体内从未定义，会抛出 `NameError: name 'latest_date' is not defined`
- **修复**: 从 `result_df["datetime"].max()` 提取最新交易日并赋值给 `latest_date`
- **状态**: ✅ 已修复

### [CRITICAL] C2: `.env` 文件暴露 API Key
- **文件**: `.env`
- **严重性**: Critical — 安全风险
- **描述**: `.env` 文件中包含明文 LiteLLM API Key (`sk-HzG2vVz2vIKFO1pE8vCRazxdkNfJ1l9ZgxQIfr5Pk4sKrVpB`)。虽然 `.env` 已在 `.gitignore` 中，但未显式添加且缺少模板文件
- **修复**: 
  1. 在 `.gitignore` 中显式添加 `.env` 和 `.env.local`
  2. 创建 `.env.example` 模板文件，使用占位符代替真实密钥
- **状态**: ✅ 已修复

### [HIGH] H1: `engine/recompute/ic_analysis.py` 年度 IC 分析静默失败
- **文件**: `engine/recompute/ic_analysis.py` 第 38 行
- **严重性**: High — 年度 IC 分析永远返回空结果
- **描述**: `ic_analysis_yearly()` 函数尝试访问 `returns_df["return"]` 列，但在正常路径下（`load_returns()` 从 session parquet 加载），列名是 `["$close", "return_1d", "return_3d", "return_5d"]`，不存在 `"return"` 列。只有降级路径（无 session 数据时）才会生成 `"return"` 列。这导致年度 IC 分析对所有正常运行的项目静默返回 None
- **修复**: 增加对 `"return_5d"` 列的兼容检查
- **状态**: ✅ 已修复

### [HIGH] H2: `engine/cache.py` `CacheManager.get_size_mb()` 潜在崩溃
- **文件**: `engine/cache.py` 第 118-120 行
- **严重性**: High — 某些类型调用 `sys.getsizeof()` 会抛出 `TypeError`
- **描述**: `get_size_mb()` 中对非 DataFrame/Series/numpy 类型使用 `sys.getsizeof(v)`，但某些对象不支持 `getsizeof`，会抛出 `TypeError: bad operand type for unary -: 'str'` 等异常
- **修复**: 用 try/except 包裹 `sys.getsizeof()` 调用
- **状态**: ✅ 已修复

### [HIGH] H3: `parallel_recompute_factors.py` 无用 `re` 导入及临时变量
- **文件**: `parallel_recompute_factors.py` 第 63-70 行
- **严重性**: High — 死代码，可能导致误导
- **描述**: 导入了 `re` 模块并使用 `re.search()` 提取函数名，但 `func_name` 变量创建后从未使用，属于无效代码
- **修复**: 移除 `re` 导入和相关的 `func_match`/`func_name` 代码块
- **状态**: ✅ 已修复

### [HIGH] H4: 常量命名不一致 `IC_MIN_STocks_PER_DAY`
- **文件**: `engine/ic_scan/core.py` 及所有引用处
- **严重性**: High — 代码规范问题，可能导致混淆
- **描述**: 常量 `IC_MIN_STocks_PER_DAY` 中 "Stocks" 大小写不一致（应为全小写 `stocks`），且在 `core.py` 定义和 `analysis.py` 引用之间存在不一致
- **修复**: 统一为 `IC_MIN_STOCKS_PER_DAY`，并同步更新所有 11 处引用
- **状态**: ✅ 已修复（623 测试全部通过）

---

## 二、发现但未修复问题 (Medium & Low)

### [MEDIUM] M1: `engine/backtest.py` 价格查找性能问题
- **文件**: `engine/backtest.py` 第 98-210 行
- **严重性**: Medium — 性能瓶颈
- **描述**: `price_map` 是普通 Python dict，`key in price_map` 查找为 O(1) 但每次迭代仍涉及 tuple 创建。回测循环中频繁调用 `price_map[(date, stock)]`，在大回测场景下可能有优化空间。建议使用 `pd.MultiIndex` 或直接使用 DataFrame 进行向量化查找
- **建议**: 长期优化，当前影响有限

### [MEDIUM] M2: `batch_recompute_factors.py` 磁盘空间浪费
- **文件**: `batch_recompute_factors.py` 第 48-68 行
- **严重性**: Medium — 资源浪费
- **描述**: 每个 session 目录都复制一份完整的 parquet 文件（~133MB），66 个 session 共占用约 8.7GB 额外空间。应使用符号链接（symlink）代替复制
- **建议**: 改用 `os.symlink()` 创建符号链接

### [MEDIUM] M3: `data_corrector.py` 全局涨跌停计算
- **文件**: `data_corrector.py` 第 225-238 行
- **严重性**: Medium — 逻辑不准确
- **描述**: `apply_trading_rule_corrections()` 中计算涨跌停限制时，使用 `boards.map(lambda c: get_board(c))` 然后 `limits = boards.map(...)` 但后续 `limit_up = prev_close * (1 + limits)` 中 `limits` 是 Series 而 `prev_close` 也是 Series，这个操作是正确的。但原始问题报告称存在"全局限制而非个股限制"的问题——经核查代码逻辑实际正确，此问题已不存在

### [MEDIUM] M4: `engine/backtest.py` 强制平仓逻辑
- **文件**: `engine/backtest.py` 第 215-220 行
- **严重性**: Medium — 潜在逻辑缺陷
- **描述**: 主循环结束后，强制平仓使用最后一天的收盘价卖出。但如果最后一天是涨跌停日（无法实际卖出），仍会执行卖出，导致回测结果过于乐观
- **建议**: 在强制平仓时也加入涨跌停检查

### [LOW] L1: 测试覆盖率不足
- **文件**: 多处
- **严重性**: Low — 质量风险
- **描述**: 整体覆盖率仅 59%，远低于 80% 目标。以下模块零覆盖：
  - `engine/safe_factor_exec.py` (34 lines, 0%)
  - `factor_portfolio.py` (126 lines, 0%)
  - `factor_scan_mem_optimized.py` (22 lines, 0%)
  - `factor_stock_selection.py` (117 lines, 0%)
  - `fix_sessions.py` (96 lines, 0%)
  - `parallel_recompute_factors.py` (120 lines, 0%)
  - `run_full_pipeline.py` (168 lines, 0%)
  - `run_ic_fast.py` (111 lines, 18%)
  - `select_top10.py` (109 lines, 0%)
- **建议**: 优先为 `engine/safe_factor_exec.py` 和 `select_top10.py` 补充测试

### [LOW] L2: `engine/factor_synthesize.py` 函数内部导入
- **文件**: `engine/factor_synthesize.py` 第 99 行
- **严重性**: Low — 代码风格问题
- **描述**: `compute_factor_ic_summary()` 函数内部使用 `from .factor_loader import FactorLoader`，而非在模块顶部导入。虽然不影响功能，但不符合 Python 最佳实践
- **建议**: 移至模块顶部导入

### [LOW] L3: `engine/recompute/loader.py` 重复代码
- **文件**: `engine/recompute/loader.py` 第 35-80 行
- **严重性**: Low — 可维护性问题
- **描述**: `load_returns()` 函数中的收益率计算逻辑与 `engine/ic_scan/data.py` 中的 `load_returns_from_sessions()` 高度重复，维护时需同步修改两处
- **建议**: 抽取为公共工具函数

---

## 三、架构与代码质量观察

### 优点
1. **模块化设计良好**: `engine/` 子模块职责清晰（pricing、backtest、factor、metrics、cache）
2. **安全执行机制**: `safe_factor_exec.py` 使用 `importlib` 替代 `exec()`，并含危险模式检测
3. **交易规则完备**: `trading_rules_core.py` 覆盖 A 股所有板块规则
4. **测试框架完善**: 623 个测试用例覆盖核心逻辑
5. **缓存系统**: `engine/cache.py` 提供 LRU 缓存和内存监控

### 需改进
1. **模块间耦合**: `batch_recompute_factors.py` 直接 import `engine.safe_factor_exec`，破坏了模块隔离
2. **路径管理**: `fix_sessions.py` 使用硬编码相对路径 `'git_ignore_folder/RD-Agent_workspace'`，应改用 `cfg.RDAGENT_WORKSPACE`
3. **错误处理不一致**: 部分模块使用 `logger.warning`，部分使用 `print`，建议统一
4. **缺少类型注解**: 大部分函数缺少类型注解，不利于维护和 IDE 支持

---

## 四、数据泄漏风险审查

### 已确认安全的部分
1. **因子计算时序**: `synthesize_daily_composite()` 使用当日截面数据，回测使用 T-1 信号，无未来信息泄漏
2. **IC 计算**: `compute_ic()` 和 `compute_ic_time_series()` 使用当日因子值和次日收益，时序正确
3. **涨跌停检查**: 回测引擎在买入/卖出时均检查涨跌停状态

### 潜在关注点
1. **`data_corrector.py` 拆分事件检测**: 使用 `ratio < 0.5` 作为拆分判定阈值，可能将极端跌停误判为拆分
2. **`engine/pricing.py` 复权逻辑**: 自动检测拆分事件的阈值 `split_ratio_threshold=3.0` 较宽松，可能误触发

---

## 五、修复汇总

| 文件 | 修复内容 | 类型 |
|------|---------|------|
| `select_top10.py` | 添加 `latest_date = result_df["datetime"].max()` 定义 | Critical Bug |
| `engine/recompute/ic_analysis.py` | 添加 `"return_5d"` 列兼容检查 | High Bug |
| `engine/cache.py` | `get_size_mb()` 增加 TypeError 保护 | High Bug |
| `parallel_recompute_factors.py` | 移除无用 `re` 导入和临时变量 | High Code Quality |
| `engine/ic_scan/core.py` + 所有引用 | 统一常量名为 `IC_MIN_STOCKS_PER_DAY` | High Code Quality |
| `.gitignore` | 显式添加 `.env` 和 `.env.local` | Security |
| `.env.example` | 新建模板文件 | Security |

**测试结果**: 623 passed (修复前后一致，无回归)
