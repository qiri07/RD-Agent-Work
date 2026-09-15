# 数据源完整性检查

## Source 数据文件列表

| 文件名 | 行数 | 日期范围 | 股票数 | 用途 |
|--------|------|----------|--------|------|
| daily_pv.parquet | 7,450,332 | 2020-01-02 ~ 2026-09-12 | 5,240 | **当前主数据源** |
| daily_pv_full.parquet | 7,450,332 | 2020-01-02 ~ 2026-09-12 | 5,240 | 别名（同daily_pv.parquet）|
| daily_pv_full_corrected.parquet | 4,564,295 | 2018-01-02 ~ 2026-09-03 | 5,552 | 校正后数据 |
| daily_pv_backup.parquet | 1,091,943 | 2018-01-02 ~ 2026-09-01 | 60 | 备份（仅60只）|
| daily_pv_debug.parquet | 97,986 | 2022-08-31 ~ 2026-09-01 | 100 | Debug 数据 |
| daily_pv_new.parquet | 1,091,943 | 2018-01-02 ~ 2026-09-01 | 60 | 新数据（仅60只）|
| daily_pv_temp.parquet | 912,704 | 2018-01-02 ~ 2026-09-10 | 565 | 临时数据 |

## 关键发现

### 1. Session 数据来源

Session 数据（4,310,988 行，5,552 股票）与 `daily_pv_full_corrected.parquet` 最接近：
- 股票数相同：5,552
- 日期范围接近：2022-08-31 ~ 2026-09-09 vs 2018-01-02 ~ 2026-09-03

**推测**：Session 数据是从 `daily_pv_full_corrected.parquet` 裁剪而来，但裁剪逻辑可能有问题。

### 2. 当前主数据源

```
DAILY_PV_PQ = daily_pv_full.parquet  (7.45M rows, 5,240 stocks)
```

### 3. 数据不一致问题

| 对比项 | Session | Source (current) |
|--------|---------|------------------|
| 行数 | 4,310,988 | 7,450,332 |
| 日期起点 | 2022-08-31 | 2020-01-02 |
| 股票数 | 5,552 | 5,240 |
| 股票交集 | - | 14只在Source中不存在于Session |
| Session独有股票 | 326只 | - |

---

## 建议

1. **统一数据源**：确保所有 session 使用相同的 source parquet 文件
2. **重新运行因子重算**：
   ```bash
   python3 batch_recompute_factors.py --phase1
   ```
3. **验证数据一致性**：在 IC 计算前添加数据校验
