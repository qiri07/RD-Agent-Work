# 指数成分股数据获取与更新指南

## 概述

本项目已配置自动获取沪深指数成分股数据的机制，支持以下指数：
- **CSI300** (沪深300): 300 只
- **CSI500** (中证500): 500 只
- **CSI100** (中证100): 100 只 (代理: HS300 前100只)
- **SZ50** (上证50): 50 只

## 数据来源

- **实时数据**: Baostock (`query_hs300_stocks`, `query_zz500_stocks`, `query_sz50_stocks`)
- **历史快照**: 基于旧数据 (`cn_data_old_20260911`) 生成

## 文件位置

```
shared_data/qlib_data/instruments/
├── all.txt              # 全部 5240 只股票
├── csi300.txt           # 沪深300 成分股 (300 只)
├── csi500.txt           # 中证500 成分股 (500 只)
├── csi100.txt           # 中证100 成分股 (100 只)
├── sz50.txt             # 上证50 成分股 (50 只)
└── history/             # 历史快照目录
    ├── csi300_20260912.txt
    ├── csi500_20260912.txt
    └── ...
```

## 使用方法

### 手动获取当前指数成分股

```bash
cd /run/media/onai/MyDisk/Work/RD-Agent-Work
python3 scripts/fetch_index_constituents.py
```

### 生成历史快照

```bash
python3 scripts/fetch_index_constituents.py --history --years 3
```

### 定时更新 (cron)

```bash
# 添加到 crontab (每周一至周五早上9点执行)
0 9 * * 1-5 /run/media/onai/MyDisk/Work/RD-Agent-Work/scripts/cron_fetch_index.sh
```

## 数据格式

qlib 格式的 instruments 文件：
```
{股票代码}\t{开始日期}\t{结束日期}
```

示例：
```
SH600000	2026-09-12	2026-09-12
SH600009	2026-09-12	2026-09-12
```

## 已知限制

1. **历史数据**: 真实的历史成分股数据需要付费数据源（Wind、同花顺等），当前历史快照基于旧数据近似生成
2. **缺失股票**: 少数新上市股票（如 600930、300251 等）的特征文件可能缺失，覆盖率约 98%
3. **CSI100**: 使用 HS300 前100只作为代理，非官方 CSI100 成分股

## 数据更新记录

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-09-12 | 首次获取 | csi300: 300, csi500: 500, csi100: 100, sz50: 50 |
| 2026-09-12 | 生成历史快照 | 过去2年，每季度1次 |

## 相关脚本

- `scripts/fetch_index_constituents.py` - 主获取脚本
- `scripts/cron_fetch_index.sh` - 定时任务脚本
- `shared_data/meta.json` - 数据元信息
