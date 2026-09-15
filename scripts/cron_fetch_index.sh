#!/bin/bash
# 指数成分股定时获取脚本
# 添加到 crontab: 0 9 * * 1-5 /run/media/onai/MyDisk/Work/RD-Agent-Work/scripts/cron_fetch_index.sh

set -e

PROJECT_ROOT="/run/media/onai/MyDisk/Work/RD-Agent-Work"
LOG_DIR="$PROJECT_ROOT/log/index_fetch"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
LOG_FILE="$LOG_DIR/${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始获取指数成分股..." | tee -a "$LOG_FILE"

cd "$PROJECT_ROOT"
source rdagent-env/bin/activate 2>/dev/null || true

python3 scripts/fetch_index_constituents.py >> "$LOG_FILE" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 完成" | tee -a "$LOG_FILE"
