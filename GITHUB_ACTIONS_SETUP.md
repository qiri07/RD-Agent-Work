# GitHub Actions 定时任务配置指南

## 概述

每日北京时间 16:00 自动执行：
1. **IC 因子分析** — 计算所有因子的 IC / t值 / 正占比
2. **选股** — 基于 Top 因子筛选 Top 10 股票
3. **回测** — Top-10 策略回测（含复权处理）
4. **飞书推送** — 将结果推送到飞书群

## 部署步骤

### 1. 添加飞书 Webhook 到 GitHub Secrets

1. 打开仓库 `https://github.com/qiri07/RD-Agent-Work`
2. 进入 **Settings → Secrets and variables → Actions**
3. 点击 **New repository secret**
4. 填写：
   - **Name**: `FEISHU_WEBHOOK_URL`
   - **Value**: `https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook地址`

> 飞书自定义机器人 webhook 获取方式：飞书群 → 设置 → 群机器人 → 自定义机器人 → 签名校验 → 复制 webhook 地址

### 2. 配置自托管 Runner（推荐）

由于数据分析依赖本地 7.5GB 数据文件（`git_ignore_folder/`），推荐使用 **自托管 Runner**。

#### 在分析机上注册 Runner

```bash
# 1. 进入仓库目录
cd /run/media/onai/MyDisk/Work/RD-Agent-Work

# 2. 创建 runner 目录
mkdir -p runner && cd runner

# 3. 从 GitHub 获取安装脚本
#    Settings → Actions → Runners → New self-hosted runner
#    按页面提示下载并解压

# 4. 配置并启动
./config.sh --url https://github.com/qiri07/RD-Agent-Work \
            --token <从GitHub获取的token> \
            --labels linux,rd-agent
./run.sh
```

#### 使用 GitHub 云端 Runner（无本地数据场景）

如果没有自托管 Runner，workflow 会自动失败（因为缺少数据文件）。
可以改为仅触发飞书通知模式（需手动上传结果文件）：

```bash
# 手动触发
gh workflow run daily_analysis.yml \
  --ref main \
  --field FEISHU_WEBHOOK_URL="https://..."
```

### 3. 验证 Workflow

```bash
# 手动触发测试
gh workflow run daily_analysis.yml

# 查看运行状态
gh run watch --repo qiri07/RD-Agent-Work

# 查看日志
gh run view <run-id> --log-failed --repo qiri07/RD-Agent-Work
```

## Cron 时间表

| 配置 | 值 |
|------|-----|
| 时区 | UTC（北京时间 +8h） |
| 触发时间 | 每天 16:00 北京时间 = 08:00 UTC |
| Cron 表达式 | `0 8 * * *` |

如需调整时间，修改 `.github/workflows/daily_analysis.yml` 中的 cron 表达式：

```yaml
# 示例：每天上午 9:00 北京时间
schedule:
  - cron: '0 1 * * *'   # UTC 01:00 = 北京时间 09:00

# 示例：工作日（周一至周五）16:00
schedule:
  - cron: '0 8 * * 1-5'
```

## 故障排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Runner 未找到 | 未注册自托管 Runner | 按步骤 2 注册 |
| 飞书推送失败 | Webhook URL 错误 | 检查 GitHub Secrets 中的 URL |
| 数据文件不存在 | -runner 无法访问 git_ignore_folder | 确认 Runner 机器上有完整数据 |
| 依赖安装失败 | 网络问题 | 在 Runner 机器上预装依赖 |

## 结果文件

每次运行后，以下文件会被生成并推送到飞书：

- `ic_scan_results_new.csv` — IC 分析结果
- `top10_stocks_new.csv` — Top 10 选股
- `backtest_nav.csv` — 回测净值曲线
- `backtest_trades.csv` — 回测交易明细

飞书消息格式：
```
📈 RD-Agent 因子分析与选股报告
🕐 2026-09-04 16:00:00

━━━ 📊 因子 IC 分析 ━━━
分析因子数: 56
有效交易日: 967 天
平均 |IC|:  0.0234

Top 5 因子:
  🟢 #1 Momentum_5d_v2  IC=+0.0717  t=4.12
  ...

━━━ 🎯 Top 10 选股 ━━━
  1. SH600653  得分=4.371
  ...
```

## 手动运行

```bash
# 手动触发一次完整流程
gh workflow run daily_analysis.yml --ref main

# 只运行 IC 分析
python run_pipeline.py --ic-only

# 只选股（用已有 IC 结果）
python run_pipeline.py --stocks-only

# 只推送飞书
python run_pipeline.py --feishu-only
```
