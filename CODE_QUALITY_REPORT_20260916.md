# 项目代码质量检查报告

> 检查日期: 2026-09-16  
> 检查范围: 核心模块 + 测试套件 (152 个 Python 文件)

---

## 📊 总体评估

| 指标 | 评分 | 说明 |
|------|------|------|
| **测试通过率** | ⭐⭐⭐⭐⭐ | 623/623 全部通过 |
| **代码规范** | ⭐⭐⭐⭐⭐ | flake8 零问题，无 bare except |
| **类型注解** | ⭐⭐⭐⭐☆ | 核心模块均有注解 |
| **安全检查** | ⭐⭐⭐⭐☆ | exec() 已替换，Docker socket 待清理 |
| **功能完整性** | ⭐⭐⭐⭐☆ | 全流程可用，缺测试覆盖 |
| **综合评分** | **4.0 / 5** | 上次 3.5 → 本轮 +0.5 |

---

## ✅ 本轮已修复（2026-09-16）

| 问题 | 状态 | 详情 |
|------|------|------|
| FactorEngine.load_factor 绑定错误 | ✅ 已修复 | 类属性赋值改为显式委托方法 |
| factor_loader.py 仅支持 h5 | ✅ 已修复 | 增加 parquet 回退支持 |
| backtest_top10.py 空 daily_value KeyError | ✅ 已修复 | 增加空值检查 |
| run_full_pipeline.py initial_nav 属性不存在 | ✅ 已修复 | 改为从 final_nav 反推 |
| factor_synthesize.py 日期选择不当 | ✅ 已修复 | 取所有因子公共最新日期 |
| exec() 注入安全 | ✅ 已修复 | 5 处全部替换为 importlib |
| cache.py get_size_mb 内存估算 | ✅ 已修复 | 改用 memory_usage(deep=True) |
| 新增数据时效检查 | ✅ 已完成 | engine/data_freshness.py |
| 新增全量股票回测 | ✅ 已完成 | backtest_all_stocks.py |

---

## 🔴 P0 待修复

### S1: Docker Socket 暴露
**文件**: `docker-proxy.py`, `docker-http-proxy.py`
```python
# 将 Docker socket 通过 HTTP 暴露，无任何认证
SYSTEM_DOCKER = 'http+unix://%2Fvar%2Frun%2Fdocker.sock'
os.chmod(sock_path, 0o666)
```
**风险**: 网络可达即可执行任意 Docker 命令  
**建议**: 立即移除或添加 mTLS 认证

### C3: __all__ 暴露内部函数
**文件**: `engine/__init__.py`
```python
# 以下内部编排函数不应暴露到公共 API
'run_phase1_recompute',
'run_phase2_ic_analysis',
```
**建议**: 从 `__all__` 中移除

### H5: 双回测引擎不一致
| 引擎 | 路径 | 差异 |
|------|------|------|
| 主引擎 | `engine/backtest.py` | 标准实现 |
| 旧引擎 | `analyze_market/backtest.py` | T+1/止损/费用逻辑不一致 |
| 独立引擎 | `stock_analyzer/backtest.py` | 独立实现，未复用 engine |
**建议**: 统一使用 `engine/backtest.py`，废弃另两个

---

## 🟠 P1 优化项

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| 1 | `engine/ic_scan/*.py` vs `ic_compute.py` | 两套 IC 计算，阈值不一致 | 选定权威版本 |
| 2 | `run_full_pipeline.py:12-16` | `engine/ic_scan.py`/`engine/recompute.py` 纯代理文件 | 删除，直接导入子模块 |
| 3 | 缺失 `test_data_freshness.py` | 新增 data_freshness 无测试 | 补充 |
| 4 | 缺失 `test_backtest_all_stocks.py` | 新增脚本无测试 | 补充 |
| 5 | 涨跌停检查无测试 | `engine/backtest.py` 核心逻辑 | 补充 |

---

## 🟡 P2 维护项

| # | 位置 | 问题 |
|---|------|------|
| 1 | 多处 | 魔法数字散落（10000, 100, 50 等），建议统一放 config.py |
| 2 | `engine/cache.py` | CacheManager 超限只警告不淘汰 |
| 3 | `data_corrector.py` | 5次连续 `.copy()` 750万行 → 内存峰值 |
| 4 | `ic_compute.py` | O(D×S) Python 循环 → 向量化已部分完成 |

---

## 📁 核心模块健康度

| 模块 | 行数 | 函数数 | 类型注解 | 测试 |
|------|------|--------|---------|------|
| `engine/backtest.py` | 343 | 7 | ✅ | ⚠️ 涨跌停待补充 |
| `engine/factor.py` | 86 | 10 | ✅ | ✅ |
| `engine/factor_loader.py` | 91 | 4 | ✅ | ✅ |
| `engine/factor_synthesize.py` | 213 | 5 | ✅ | ⚠️ 边界条件待补充 |
| `engine/metrics.py` | 196 | 7 | ✅ | ⚠️ analyze_period 待补充 |
| `engine/pricing.py` | 134 | 8 | ✅ | ✅ |
| `engine/cache.py` | 140 | 14 | ✅ | ⚠️ 内存估算待补充 |
| `engine/data_freshness.py` | 136 | 3 | ✅ | ❌ 无测试 |
| `engine/safe_factor_exec.py` | 78 | 2 | ✅ | ✅ |
| `ic_compute.py` | 193 | 5 | ✅ | ✅ |
| `run_full_pipeline.py` | 291 | 8 | ✅ | ✅ |
| `backtest_top10.py` | 220 | 2 | 部分 | ✅ |
| `backtest_all_stocks.py` | 262 | 2 | ✅ | ❌ 无测试 |
| `feishu_notify.py` | 225 | 5 | ✅ | ✅ |
| `config.py` | 134 | 2 | ✅ | ✅ |

---

## 🔒 安全检查

| 检查项 | 状态 |
|--------|------|
| exec() 注入风险 | ✅ 已替换为 importlib + 代码白名单校验 |
| Docker Socket 暴露 | ⚠️ docker-proxy.py 仍存在 |
| Pickle 反序列化 | ⚠️ convert_tradero_to_rdagent.py |
| 路径注入 | ⚠️ subprocess f-string 拼接 |
| bare except | ✅ 全部清除 |
| 魔法字符串 | ⚠️ 部分散落 |

---

## 📈 变更历史

| 日期 | 提交 | 主要变更 |
|------|------|---------|
| 2026-09-16 | `3ec0f67` | 全量股票回测 Top N |
| 2026-09-16 | `262aaff` | 数据时效检查 + 飞书推送 |
| 2026-09-16 | `b94deb5` | FactorEngine 修复 + 多文件兼容 |
| 2026-09-15 | `6bf57cd` | 全面修复: 安全/性能/测试/架构 |
