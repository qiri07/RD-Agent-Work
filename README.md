# RD-Agent 因子分析平台

A-factor analysis and stock selection platform for A-share (Chinese equity) markets, built on top of the [RD-Agent](https://github.com/rd-agent/rd-agent) framework.

## Overview

| Component | Description |
|-----------|-------------|
| **Factor Generation** | 66 AI-generated quantitative factors via RD-Agent |
| **IC Analysis** | Rank IC (Spearman correlation) between factors and forward returns |
| **Stock Screening** | Multi-factor composite scoring for top stock selection |
| **Backtesting** | Event-driven backtest engine with split-adjusted prices |
| **Notifications** | Feishu (Lark) webhook push for results |

## Quick Start

```bash
# Activate virtual environment
source rdagent-env/bin/activate

# Run full pipeline: IC analysis → Stock screening → Feishu push
python run_pipeline.py

# Or individual steps
python run_ic_fast.py               # IC analysis only
python full_factor_stock_selection.py  # Stock screening only
python backtest_top10.py            # Backtest top-10 strategy
python feishu_notify.py --ic-results ic_scan_results_new.csv --stocks top10_stocks_new.csv
```

## Project Structure

```
RD-Agent-Work/
├── config.py                    # Central configuration (paths, params, webhook)
├── feishu_notify.py             # Feishu webhook notification module
├── run_pipeline.py              # Unified pipeline (IC + screening + push)
├── run_ic_fast.py               # High-performance IC analysis (v5)
├── full_factor_stock_selection.py  # Multi-factor stock screening
├── backtest_top10.py            # Top-10 strategy backtest with split adjustment
├── factor_scan_mem_optimized.py # Memory-efficient factor scanner
├── analyze_factors.py           # Factor analysis utility
├── factor_portfolio.py          # Multi-factor portfolio tool
├── visualize_results.py         # Backtest result visualization
├── tests/                       # Unit tests
│   ├── test_config.py
│   ├── test_feishu_notify.py
│   └── test_ic_computation.py
├── git_ignore_folder/           # Large data files (excluded from git)
│   ├── RD-Agent_workspace/      # 66 factor sessions
│   └── factor_implementation_source_data/
│       ├── daily_pv_full.parquet  # Full price data (~1GB)
│       └── ic_scan_results_new.parquet
├── ic_scan_results_new.csv      # IC analysis results
├── top10_stocks_new.csv         # Top 10 stock selection
├── backtest_nav.csv             # Backtest NAV curve
└── backtest_trades.csv          # Backtest trade log
```

## Configuration

All configurable parameters are centralized in `config.py`. They can be overridden via environment variables:

```bash
# Example: Override backtest parameters
export BACKTEST_TOP_K=20
export BACKTEST_HOLD_DAYS=10
export BACKTEST_INITIAL_CAPITAL=2000000

# Feishu webhook
export FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `IC_MIN_DAILY_STOCKS` | 50 | Minimum stocks per day for valid IC |
| `IC_TOP_N_DEFAULT` | 10 | Default top N factors for display |
| `STOCK_TOP_K_DEFAULT` | 10 | Number of stocks to select |
| `BACKTEST_TOP_K` | 10 | Stocks held per rebalance |
| `BACKTEST_HOLD_DAYS` | 5 | Holding period in days |
| `BACKTEST_COMMISSION_RATE` | 0.0003 | Trading commission |
| `BACKTEST_SLIPPAGE_RATE` | 0.001 | Trading slippage |

## IC Analysis

Information Coefficient (IC) measures the rank correlation between a factor's cross-sectional values and forward returns.

```python
# Key metrics per factor:
# IC_5d      : Mean Spearman rank correlation with 5-day forward return
# IC_t_5d    : t-statistic of IC (significance)
# IC_pos_5d  : Percentage of days with positive IC
# n_days     : Number of valid trading days
```

Top factors are typically Momentum variants (e.g., `Momentum_5d`, `Momentum_10d`).

## Backtest Results

| Metric | Value |
|--------|-------|
| Total Return | See `backtest_nav.csv` |
| Sharpe Ratio | See `backtest_nav.csv` |
| Max Drawdown | See `backtest_nav.csv` |
| Win Rate | See `backtest_trades.csv` |

The backtest engine handles:
- Split-adjusted prices (detected automatically)
- A-share lot size (100 shares/lot)
- Commission + slippage costs
- T-1 signal timing (no look-ahead)

## Running Tests

```bash
source rdagent-env/bin/activate
python -m pytest tests/ -v
```

## Data

- **Price data**: `git_ignore_folder/factor_implementation_source_data/daily_pv_full.parquet`
  - Coverage: ~5,553 A-shares (SH + SZ), 2018-01-02 ~ 2026-08-31
  - Fields: `$open`, `$close`, `$high`, `$low`, `$volume`, `$factor`
- **Factor data**: `git_ignore_folder/RD-Agent_workspace/*/result.h5` or `result.parquet`
  - MultiIndex: `(datetime, instrument)`

## Environment

- Python 3.11+ (virtualenv: `rdagent-env/`)
- Dependencies: `pandas`, `numpy`, `scipy`, `pyarrow`, `h5py`

## License

Internal use.
