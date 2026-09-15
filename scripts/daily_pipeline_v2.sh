#!/bin/bash
# 每日因子分析流水线 v2
# 用法: bash scripts/daily_pipeline_v2.sh

set -eo pipefail

PROJECT_ROOT="/run/media/onai/MyDisk/Work/RD-Agent-Work"
LOG_DIR="$PROJECT_ROOT/log/pipeline_v2"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
LOG_FILE="$LOG_DIR/${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=========================================="
log "  因子分析流水线 v2 开始"
log "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
log "=========================================="

cd "$PROJECT_ROOT"
source rdagent-env/bin/activate 2>/dev/null || true

# Step 1: IC 分析
log "\n📊 Step 1/4: IC 因子分析..."
python3 run_ic_fast.py --feishu-url "$FEISHU_WEBHOOK_URL" 2>&1 | tee -a "$LOG_FILE"

# Step 2: 选股
log "\n🎯 Step 2/4: 选股..."
python3 run_pipeline.py --stocks-only 2>&1 | tee -a "$LOG_FILE"

# Step 3: 回测
log "\n📈 Step 3/4: 回测..."
python3 backtest_top10.py 2>&1 | tee -a "$LOG_FILE"

# Step 4: 绩效评估 + 推送
log "\n📋 Step 4/4: 绩效评估 + 飞书推送..."
python3 << 'PYEOF'
import pandas as pd
import numpy as np
from pathlib import Path
import json
from datetime import datetime

BASE = Path("/run/media/onai/MyDisk/Work/RD-Agent-Work")
from feishu_notify import send_combined_report

# 读取结果
ic_df = pd.read_csv(BASE / "ic_scan_results_new.csv")
stocks_df = pd.read_csv(BASE / "top10_stocks_new.csv")
nav_df = pd.read_csv(BASE / "backtest_nav.csv")
trades_df = pd.read_csv(BASE / "backtest_trades.csv")

# 绩效指标
initial_capital = 1_000_000
final_value = nav_df['value'].iloc[-1]
total_return = (final_value / initial_capital - 1) * 100

nav_df['date'] = pd.to_datetime(nav_df['date'])
start_date = nav_df['date'].iloc[0]
end_date = nav_df['date'].iloc[-1]
total_days = (end_date - start_date).days
years = total_days / 365.25
annual_return = ((final_value / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else total_return

nav_df = nav_df.set_index('date').sort_index()
daily_ret = nav_df['value'].pct_change().dropna()
sharpe = (daily_ret.mean() * 252 - 0.02) / (daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0

nav = nav_df['value']
running_max = nav.cummax()
drawdown = (nav - running_max) / running_max
max_drawdown = drawdown.min() * 100

sells = trades_df[trades_df['action'] == 'SELL']
wins = sells[sells['pnl_pct'] > 0]
win_rate = len(wins) / len(sells) * 100 if len(sells) > 0 else 0

# 生成报告
report = f"""📊 因子分析流水线报告
{'='*50}
🕐 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📈 数据源: shared_data/ (5240只)

【IC 因子分析】
• 有效因子数: {len(ic_df)}
• Top 3 因子:
"""
for i, (_, row) in enumerate(ic_df.head(3).iterrows(), 1):
    report += f"  {i}. IC={row['IC_5d']:+.4f}  t={row['IC_t_5d']:+.2f}\n"

report += f"""
【选股结果】(Top 5)
"""
for i, (_, row) in enumerate(stocks_df.head(5).iterrows(), 1):
    report += f"  {i}. {row['instrument']}  得分={row['composite_score']:.2f}\n"

report += f"""
【回测绩效】
• 周期: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')} ({total_days}天)
• 总收益: {total_return:+.2f}%
• 年化: {annual_return:+.2f}%
• 夏普: {sharpe:.3f}
• 回撤: {max_drawdown:.2f}%
• 胜率: {win_rate:.1f}%
"""

# 保存报告
(BASE / "pipeline_report.txt").write_text(report)
print(report)

# 推送飞书
try:
    success = send_combined_report(ic_df, stocks_df, top_n=10)
    print(f"\n✅ 飞书推送: {'成功' if success else '失败'}")
except Exception as e:
    print(f"\n⚠️ 飞书推送失败: {e}")

# 保存摘要
summary = {
    'timestamp': datetime.now().isoformat(),
    'ic_factors': len(ic_df),
    'top_stocks': stocks_df.head(10)[['instrument', 'composite_score']].to_dict('records'),
    'backtest': {
        'total_return_pct': float(total_return),
        'annual_return_pct': float(annual_return),
        'sharpe_ratio': float(sharpe),
        'max_drawdown_pct': float(max_drawdown),
        'win_rate_pct': float(win_rate)
    }
}
with open(BASE / "pipeline_summary.json", 'w') as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)
PYEOF

log ""
log "=========================================="
log "  流水线完成! 日志: $LOG_FILE"
log "=========================================="
