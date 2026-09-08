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
| **Data Validation** | Price/correction validator with trading rule enforcement |

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
python batch_recompute_factors.py --phase2  # Recompute all factors
```

## Project Structure

```
RD-Agent-Work/
├── config.py                    # Central configuration (paths, params, webhook)
│
├── trading_rules_core.py        # Board enum, limit/lot rules, limit price calc (no pandas)
├── trading_rules.py             # Aggregator wrapper + FactorRuleChecker (backward compat)
├── data_validator.py            # DataValidator: price/vol/gap/ST/split detection
├── data_corrector.py            # Auto-correction: splits, extreme prices, volume winsorize
├── factor_rule_corrector.py     # Factor-level trading rule enforcement
│
├── ic_compute.py                # Shared IC computation library (chunked, memory-safe)
├── memory_utils.py              # RSS monitoring, memory env setup
│
├── run_pipeline.py              # Unified pipeline (IC + screening + push)
├── run_ic_fast.py               # High-performance IC analysis (v5, per-session)
├── run_ic_scan.py               # IC scan using clean debug data
├── factor_scan_mem_optimized.py # Memory-efficient factor scanner + disk cleanup
├── batch_recompute_factors.py   # Sequential factor recomputation
├── parallel_recompute_factors.py # Parallel factor recomputation (multi-process)
├── full_factor_stock_selection.py # Multi-factor stock screening
├── backtest_top10.py            # Top-10 strategy backtest with split adjustment
├── analyze_31_stocks.py         # 31-target stock analysis + backtest
├── feishu_notify.py             # Feishu webhook notification module
│
├── tests/                       # Unit tests (191 tests, 100% pass)
│   ├── test_config.py
│   ├── test_trading_rules.py
│   ├── test_data_corrector.py
│   ├── test_data_validator.py
│   ├── test_factor_rule_corrector.py
│   ├── test_ic_computation.py
│   ├── test_ic_compute.py
│   ├── test_parallel_recompute.py
│   ├── test_batch_recompute.py
│   ├── test_pipeline_and_dedup.py
│   └── test_feishu_notify.py
├── git_ignore_folder/           # Large data files (excluded from git)
│   ├── RD-Agent_workspace/      # 66 factor sessions
│   └── factor_implementation_source_data/
│       ├── daily_pv_full.parquet   # Deduplicated price data (~1GB)
│       └── ic_scan_results_new.parquet
│
├── ic_scan_results_new.csv    # IC analysis results
├── top10_stocks_new.csv       # Top 10 stock selection
├── daily_pipeline.sh          # Cron automation script
└── FULL_REVIEW_REPORT.md      # Comprehensive review report
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

# trade-krono-cli cache path (for convert_tradero_to_rdagent.py)
export TRADERO_CACHE_DB=/path/to/pipeline_cache.db
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
| `IC_BATCH_SIZE` | 100 | IC batch size for daily processing |

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
- Split-adjusted prices (detected automatically via price ratio > 3.0)
- A-share lot size (100 shares/lot, 200 for STAR)
- Commission + slippage costs
- T-1 signal timing (no look-ahead)

## Data Validation & Correction

The platform includes automated data quality checks:

| Module | Function |
|--------|----------|
| `data_validator.py` | Detects extreme prices, return violations, volume anomalies, gap anomalies, ST suspects, split events |
| `data_corrector.py` | Applies corrections: split adjustment, extreme price clip, volume winsorize |
| `factor_rule_corrector.py` | Applies trading rules to factor calculations (limit status, tradeable filter) |

## Running Tests

```bash
source rdagent-env/bin/activate
python -m pytest tests/ -v            # All tests with details
python -m pytest tests/ -q            # Quiet mode
python -m pytest tests/ --cov=.       # With coverage report
```

**Current test coverage: 191 tests, 100% pass rate**

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_trading_rules.py` | 41 | 99% |
| `test_batch_recompute.py` | 18 | 97% |
| `test_data_corrector.py` | 18 | 98% |
| `test_data_validator.py` | 16 | 99% |
| `test_ic_compute.py` | 15 | 99% |
| `test_parallel_recompute.py` | 10 | 99% |
| `test_pipeline_and_dedup.py` | 17 | 95% |
| `test_config.py` | 9 | 99% |
| `test_ic_computation.py` | 9 | 98% |
| `test_factor_rule_corrector.py` | 14 | 98% |
| `test_feishu_notify.py` | 7 | 99% |

## Data

- **Price data**: `git_ignore_folder/factor_implementation_source_data/daily_pv_full.parquet`
  - Coverage: ~5,553 A-shares (SH + SZ), 2018-01-02 ~ 2026-08-31
  - Fields: `$open`, `$close`, `$high`, `$low`, `$volume`, `$factor`
- **Factor data**: `git_ignore_folder/RD-Agent_workspace/*/result.h5` or `result.parquet`
  - MultiIndex: `(datetime, instrument)`
- **Returns**: Pre-computed 5-day forward returns in `returns_5d.h5` / `returns_5d.parquet`

## Environment

- Python 3.11+ (virtualenv: `rdagent-env/`)
- Dependencies: `pandas`, `numpy`, `scipy`, `pyarrow`, `h5py`

## Recent Updates (2026-09-08)

- **Bug fixes**: Fixed int64 `LossySetitemError` in volume winsorize (`data_corrector.py`, `factor_rule_corrector.py`, `data_validator.py`)
- **Bug fixes**: Fixed `.iloc[0]` crash on scalar MultiIndex lookup (`data_corrector.py`)
- **Bug fixes**: Fixed key mismatch in `get_correction_recommendations()` (`trading_rules.py`)
- **Architecture**: Extracted `trading_rules_core.py` (pure rules, no pandas), `data_validator.py`, `ic_compute.py`, `memory_utils.py`
- **Tests**: Added 39 new tests; total 191, all passing
- **Security**: All hardcoded paths externalized via `config.py` / environment variables

## License

Internal use.
