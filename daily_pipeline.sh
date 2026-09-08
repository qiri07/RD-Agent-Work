#!/bin/bash
# 每日因子流水线自动化脚本
# 用法: bash daily_pipeline.sh
# crontab: 30 16 * * 1-5 cd /path/to/project && bash daily_pipeline.sh

set -e

PROJECT_ROOT="/run/media/onai/MyDisk/Work/RD-Agent-Work"
LOG_DIR="$PROJECT_ROOT/log"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
LOG_FILE="$LOG_DIR/${TIMESTAMP}/pipeline.log"
SUMMARY_FILE="$LOG_DIR/${TIMESTAMP}/summary.json"

mkdir -p "$LOG_DIR/$TIMESTAMP"

log() {
    echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=========================================="
log "  每日因子流水线开始"
log "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
log "=========================================="

cd "$PROJECT_ROOT"
source rdagent-env/bin/activate

TOTAL_START=$(date +%s)

# ── 步骤 0: 数据质量检查与矫正 ───────────────────────
log "\n🔍 步骤 0/5: 数据质量检查与矫正..."
STEP0_START=$(date +%s)

python3 data_corrector.py --dry-run 2>&1 | tee -a "$LOG_FILE"

STEP0_END=$(date +%s)
log "  ✅ 数据质量检查完成 (${(($STEP0_END - $STEP0_START))}s)"

# ── 步骤 1: 增量更新数据 ──────────────────────────────
log "\n📥 步骤 1/5: 增量下载今日数据..."
STEP1_START=$(date +%s)

if [ -f "download_full_astock.py" ]; then
    python3 download_full_astock.py 2>&1 | tee -a "$LOG_FILE"
else
    log "  ⚠️  download_full_astock.py 不存在，跳过下载"
fi

STEP1_END=$(date +%s)
log "  ✅ 数据更新完成 (${(($STEP1_END - $STEP1_START))}s)"

# ── 步骤 2: 批量重算因子 ──────────────────────────────
log "\n🧮 步骤 2/5: 批量重算因子..."
STEP2_START=$(date +%s)

python3 batch_recompute_factors.py --phase2 2>&1 | tee -a "$LOG_FILE"

STEP2_END=$(date +%s)
log "  ✅ 因子重算完成 (${(($STEP2_END - $STEP2_START))}s)"

# ── 步骤 3: IC 分析 + 选股 ────────────────────────────
log "\n📊 步骤 3/5: IC 分析 + 选股..."
STEP3_START=$(date +%s)

python3 run_ic_fast.py 2>&1 | tee -a "$LOG_FILE"

STEP3_END=$(date +%s)
log "  ✅ IC 分析完成 (${(($STEP3_END - $STEP3_START))}s)"

# ── 步骤 4: 选股 + 飞书推送 ───────────────────────────
log "\n📱 步骤 4/5: 选股 + 飞书推送..."
STEP4_START=$(date +%s)

python3 run_pipeline.py --stocks-only 2>&1 | tee -a "$LOG_FILE"

STEP4_END=$(date +%s)
log "  ✅ 选股+飞书完成 (${(($STEP4_END - $STEP4_START))}s)"
TOTAL_END=$(date +%s)
TOTAL_ELAPSED=$((TOTAL_END - TOTAL_START))

log "\n=========================================="
log "  流水线完成!"
log "  总耗时: ${TOTAL_ELAPSED}s ($(printf '%dm%ds' $((TOTAL_ELAPSED/60)) $((TOTAL_ELAPSED%60))))"
log "  日志: $LOG_FILE"
log "=========================================="

# 检查数据新鲜度
LATEST_DATE=$(python3 -c "
import pandas as pd
df = pd.read_parquet('git_ignore_folder/factor_implementation_source_data/daily_pv_full.parquet')
print(df.index.get_level_values('date').max().date())
" 2>/dev/null || echo "unknown")
log "  最新数据日期: $LATEST_DATE"

# 保存摘要
python3 -c "
import json, datetime
summary = {
    'timestamp': datetime.datetime.now().isoformat(),
    'total_elapsed_s': $TOTAL_ELAPSED,
    'step1_download_s': $((STEP1_END - STEP1_START)),
    'step2_recompute_s': $((STEP2_END - STEP2_START)),
    'step3_ic_s': $((STEP3_END - STEP3_START)),
    'step4_feishu_s': $((STEP4_END - STEP4_START)),
    'log_file': '$LOG_FILE',
    'latest_date': '$LATEST_DATE',
    'status': 'success'
}
with open('$SUMMARY_FILE', 'w') as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)
print('  💾 摘要已保存:', '$SUMMARY_FILE')
" 2>/dev/null

# 清理旧日志（保留最近30天）
find "$LOG_DIR" -maxdepth 1 -type d -name "*" | \
    while read d; do
        dname=$(basename "$d")
        if [[ "$dname" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2} ]]; then
            ddate=$(echo "$dname" | cut -d_ -f1)
            dsecs=$(date -d "$ddate" +%s 2>/dev/null || echo 0)
            nowsecs=$(date +%s)
            age_days=$(( (nowsecs - dsecs) / 86400 ))
            if [ $age_days -gt 30 ]; then
                rm -rf "$d"
                log "  🗑️  清理旧日志: $dname"
            fi
        fi
    done 2>/dev/null

exit 0
