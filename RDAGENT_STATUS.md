# RD-Agent 运行环境状态报告

## ✅ 已完成配置

| 组件 | 版本 | 状态 |
|------|------|------|
| Python | 3.11.15 | ✅ 正常 |
| RD-Agent | v0.8.0 | ✅ 已安装并 patch |
| litellm | - | ✅ 已安装 |
| Ollama | - | 🔄 运行中 |
| A股数据 | BaoStock | ✅ 已接入 |

## 📊 RD-Agent 因子研发成果 (最新更新: 2026-09-02)

### 因子工作流状态
| 指标 | 数值 |
|------|------|
| 总结果数 | 52 (result.h5) |
| 因子实现 | 66 (factor.py) |
| 本次新增 | +43 个因子 |
| 成功率 | 78.8% (52/66) |

### 因子类型分布
- **Momentum (动量)**: 24个因子 (36.4%)
- **Volume (成交量)**: 18个因子 (27.3%)
- **Return (收益率)**: 10个因子 (15.1%)
- **Reversal (反转)**: 3个因子 (4.5%)
- **Other (其他)**: 11个因子 (16.7%)

### 可用工具
- `analyze_factors.py` - 因子分析工具
- `factor_portfolio.py` - 因子组合工具
- `factor_usage_example.py` - 使用示例脚本

### 生成的数据文件
- `all_available_factors.h5` - 42个可用因子数据
- `combined_factors.h5` - 多因子组合数据
- `momentum_backtest.csv` - 动量策略回测结果
- `mixed_strategy_backtest.csv` - 混合策略回测结果

详细使用指南请查看: `FACTOR_USAGE_GUIDE.md` 和 `FACTOR_WORKFLOW_ANALYSIS.md`

## A股数据接入详情

| 项目 | 内容 |
|------|------|
| 数据源 | [BaoStock](http://baostock.com) - 免费 A股历史数据接口 |
| 时间范围 | 2018-01-02 ~ 2026-08-31（2102个交易日） |
| 股票数量 | 483只 A股（上证SH + 深证SZ） |
| 数据格式 | HDF5 (MultiIndex: instrument × date) |
| 主数据 | `git_ignore_folder/factor_implementation_source_data/daily_pv.h5` (49MB) |
| 调试数据 | `git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5` (10MB) |
| 下载脚本 | `download_astock_data.py` |
| 数据字段 | $open, $close, $high, $low, $volume, $factor |

### 重新下载数据
```bash
python3 download_astock_data.py [股票数量] [开始日期] [结束日期]
# 示例: python3 download_astock_data.py 500
```

## ❌ 阻塞问题

### 1. Docker 权限不足
```
错误: permission denied while trying to connect to the docker API
解决: sudo chmod 666 /var/run/docker.sock
```

### 2. LLM 模型下载缓慢
- 网络限制导致下载速度约 1-1.3 MB/s
- qwen2.5:7b (986MB) 预计需要 15-20 分钟
- qwen2:0.5b (约 1GB) 正在下载中

### 3. OpenAI API 不可达
- 网络超时，无法访问 api.openai.com
- 已切换到本地 Ollama 后端

## 📋 可用命令

```bash
cd /run/media/onai/MyDisk/Work/RD-Agent-Work
source rdagent-env/bin/activate

# 量化因子研发
rdagent fin_factor --step_n 1 --loop_n 1

# 量化模型研发
rdagent fin_model --step_n 1 --loop_n 1

# 通用模型研发
rdagent general_model --step_n 1 --loop_n 1

# 健康检查
rdagent health_check
```

## 🔧 下一步操作

1. **修复 Docker 权限**（必须）:
   ```bash
   sudo chmod 666 /var/run/docker.sock
   ```

2. **等待模型下载完成**:
   ```bash
   # 检查进度
   curl -s http://localhost:11434/api/tags
   du -sh ~/.ollama/models/
   ```

3. **运行测试**:
   ```bash
   ./rdagent_work.sh health_check --no-check-docker
   ./rdagent_work.sh general_model --step_n 1 --loop_n 1
   ```

## 📁 文件位置

- 虚拟环境: `/run/media/onai/MyDisk/Work/RD-Agent-Work/rdagent-env/`
- 配置文件: `/run/media/onai/MyDisk/Work/RD-Agent-Work/.env`
- 工作目录: `/run/media/onai/MyDisk/Work/git_ignore_folder/`
- 包装脚本: `/run/media/onai/MyDisk/Work/RD-Agent-Work/rdagent_work.sh`
- 数据下载脚本: `/run/media/onai/MyDisk/Work/RD-Agent-Work/download_astock_data.py`

## 更新记录

### 2026-09-01 21:55
- ✅ A股真实数据已接入 (483只股票，2018-2026年)
- ✅ 数据格式符合 RD-Agent factor_coder 要求
- 🔄 数据来自 BaoStock API（后复权日线数据）

### 2026-09-01 12:15
- ✅ Ollama 服务已启动
- 🔄 gemma:2b 模型下载中 (11MB/1.7GB)
- ⚠️ 网络限制导致下载速度慢 (~1.2 MB/s)
- ⚠️ Docker 权限仍需修复

### 解决方案
1. **Docker 权限**: `sudo chmod 666 /var/run/docker.sock`
2. **模型下载**: 等待约 23 分钟，或使用代理加速
3. **替代方案**: 如有可用的国内 LLM API，可修改 .env 配置

### 可用命令（修复 Docker 后）
```bash
./rdagent_work.sh fin_factor --step_n 1 --loop_n 1
./rdagent_work.sh general_model --step_n 1 --loop_n 1
./rdagent_work.sh health_check
```
