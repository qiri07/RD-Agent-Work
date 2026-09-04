#!/usr/bin/env python3
"""
项目配置模块 — 统一管理路径、密钥、魔法数字
============================================
所有写死的路径、密钥、参数统一在此配置。

环境变量优先级 > 默认值。敏感信息必须通过环境变量注入。
"""
import os
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 项目根目录
# ═══════════════════════════════════════════════════════════
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/run/media/onai/MyDisk/Work/RD-Agent-Work"))

# ═══════════════════════════════════════════════════════════
# 数据路径
# ═══════════════════════════════════════════════════════════
GIT_IGNORE = PROJECT_ROOT / "git_ignore_folder"
FACTOR_SOURCE = GIT_IGNORE / "factor_implementation_source_data"
FACTOR_SOURCE_DEBUG = GIT_IGNORE / "factor_implementation_source_data_debug"
RDAGENT_WORKSPACE = GIT_IGNORE / "RD-Agent_workspace"

# 主要数据文件
DAILY_PV_FULL_PQ = FACTOR_SOURCE / "daily_pv_full.parquet"
DAILY_PV_PQ = FACTOR_SOURCE / "daily_pv.parquet"
IC_RESULTS_NEW_PQ = FACTOR_SOURCE / "ic_scan_results_new.parquet"
IC_RESULTS_NEW_CSV = PROJECT_ROOT / "ic_scan_results_new.csv"
TOP10_STOCKS_CSV = PROJECT_ROOT / "top10_stocks_new.csv"
FULL_STOCK_SELECTION_CSV = PROJECT_ROOT / "full_factor_stock_selection.csv"

# ═══════════════════════════════════════════════════════════
# 飞书 Webhook
# ═══════════════════════════════════════════════════════════
# 优先级：FEISHU_WEBHOOK_URL 环境变量 > token_step.txt 文件 > 占位符
_FEISHU_ENV = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
if _FEISHU_ENV:
    FEISHU_WEBHOOK_URL = _FEISHU_ENV
else:
    # 从 token_step.txt 读取（如存在）
    _token_file = Path("/run/media/onai/MyDisk/Work/files/token_step.txt")
    if _token_file.exists():
        for line in _token_file.read_text().splitlines():
            if line.startswith("FEISHU_WEBHOOK_URL="):
                _FEISHU_ENV = line.split("=", 1)[1].strip()
                if _FEISHU_ENV:
                    FEISHU_WEBHOOK_URL = _FEISHU_ENV
                    break
    else:
        FEISHU_WEBHOOK_URL = ""

# 飞书应用标识（用于消息前缀）
FEISHU_PROJECT_NAME = os.getenv("FEISHU_PROJECT_NAME", "RD-Agent 因子分析")

# ═══════════════════════════════════════════════════════════
# 因子分析参数
# ═══════════════════════════════════════════════════════════
IC_MIN_DAILY_STOCKS = int(os.getenv("IC_MIN_DAILY_STOCKS", "50"))       # 每日最少股票数阈值
IC_TOP_N_DEFAULT = int(os.getenv("IC_TOP_N_DEFAULT", "10"))             # 默认 Top N 因子展示数
IC_BATCH_SIZE = int(os.getenv("IC_BATCH_SIZE", "100"))                  # IC 逐日计算批次大小

# ═══════════════════════════════════════════════════════════
# 选股参数
# ═══════════════════════════════════════════════════════════
STOCK_TOP_K_DEFAULT = int(os.getenv("STOCK_TOP_K_DEFAULT", "10"))       # 默认选股数量
STOCK_FACTOR_TOP_N = int(os.getenv("STOCK_FACTOR_TOP_N", "10"))         # 用于选股的 Top N 因子

# ═══════════════════════════════════════════════════════════
# 回测参数
# ═══════════════════════════════════════════════════════════
BACKTEST_TOP_K = int(os.getenv("BACKTEST_TOP_K", "10"))
BACKTEST_HOLD_DAYS = int(os.getenv("BACKTEST_HOLD_DAYS", "5"))
BACKTEST_INITIAL_CAPITAL = float(os.getenv("BACKTEST_INITIAL_CAPITAL", "1000000"))
BACKTEST_COMMISSION_RATE = float(os.getenv("BACKTEST_COMMISSION_RATE", "0.0003"))
BACKTEST_SLIPPAGE_RATE = float(os.getenv("BACKTEST_SLIPPAGE_RATE", "0.001"))
BACKTEST_MIN_TRADE_VALUE = float(os.getenv("BACKTEST_MIN_TRADE_VALUE", "10000"))
BACKTEST_SPLIT_RATIO_THRESHOLD = float(os.getenv("BACKTEST_SPLIT_RATIO_THRESHOLD", "3.0"))

# 拆分日期检测（如数据中有特定拆分事件，可覆盖）
BACKTEST_SPLIT_DATE_PREV = os.getenv("BACKTEST_SPLIT_DATE_PREV")  # 格式: "YYYY-MM-DD" 或 None
BACKTEST_SPLIT_DATE_CURR = os.getenv("BACKTEST_SPLIT_DATE_CURR")

# 回测展示的时间段（用于可视化分段收益计算）
BACKTEST_PERIODS = [
    ("2022-09 ~ 2022-12", "2022-09-01", "2022-12-31"),
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026-01~08", "2026-01-01", "2026-08-31"),
    ("2026-09", "2026-09-01", "2026-09-02"),
]

# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════
def get_split_dates():
    """返回拆分日期检测的 Timestamp 对象，若未配置则返回 None"""
    from datetime import datetime
    prev = datetime.strptime(BACKTEST_SPLIT_DATE_PREV, "%Y-%m-%d") if BACKTEST_SPLIT_DATE_PREV else None
    curr = datetime.strptime(BACKTEST_SPLIT_DATE_CURR, "%Y-%m-%d") if BACKTEST_SPLIT_DATE_CURR else None
    return prev, curr


def is_feishu_configured() -> bool:
    """检查飞书 Webhook 是否已配置"""
    return bool(FEISHU_WEBHOOK_URL) and "YOUR_WEBHOOK" not in FEISHU_WEBHOOK_URL


if __name__ == "__main__":
    print("=" * 60)
    print("  项目配置校验")
    print("=" * 60)
    print(f"  项目根目录:     {PROJECT_ROOT}")
    print(f"  数据源目录:     {FACTOR_SOURCE}")
    print(f"  因子工作区:     {RDAGENT_WORKSPACE}")
    print(f"  飞书 Webhook:   {'✅ 已配置' if is_feishu_configured() else '❌ 未配置'}")
    print(f"  IC 最小股票数:   {IC_MIN_DAILY_STOCKS}")
    print(f"  默认 Top N:     {IC_TOP_N_DEFAULT}")
    print(f"  选股 Top K:     {STOCK_TOP_K_DEFAULT}")
    print(f"  回测持仓天数:   {BACKTEST_HOLD_DAYS}")
    print("=" * 60)
