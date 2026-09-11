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
├── engine/                      # Core engine modules
│   ├── __init__.py              # Unified exports
│   ├── pricing.py               # Price loading, split adjustment, returns
│   ├── backtest.py              # Event-driven backtest engine
│   ├── factor.py                # Factor loading, IC computation, synthesis
│   ├── metrics.py               # Performance metrics (Sharpe, max DD, win rate)
│   ├── cache.py                 # LRU memory cache for data loading
│   ├── recompute.py             # Phase 1 (factor recompute) + Phase 2 (IC analysis)
│   └── ic_scan.py               # compute_ic(), ic_analysis(), run_ic_scan()
├── ic_scan_utils.py             # IC scan utilities: cleanup, trace archive, size scan
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
├── run_full_recompute.py        # Full recomputation + IC analysis (thin wrapper)
├── run_factor_ic_scan.py        # Factor recompute + IC scan (thin wrapper)
├── factor_scan_mem_optimized.py # Memory-efficient scanner entry point
├── batch_recompute_factors.py   # Sequential factor recomputation
├── parallel_recompute_factors.py # Parallel factor recomputation (multi-process)
├── full_factor_stock_selection.py # Multi-factor stock screening
├── backtest_top10.py            # Top-10 strategy backtest with split adjustment
├── analyze_31_stocks.py         # 31-target stock analysis + backtest
├── feishu_notify.py             # Feishu webhook notification module
│
├── tests/                       # Unit tests (459 tests, 100% pass)
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

**Current test coverage: 459 tests, 100% pass rate**

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
| `test_backtest_single_factors.py` | 22 | 100% |
| `test_high_winrate_selection.py` | 23 | 100% |
| `test_factor_scan_mem_optimized.py` | 16 | 100% |
| `test_engine_modules.py` | 19 | 100% |
| `test_cache.py` | 37 | 100% |
| `test_metrics.py` | 17 | 100% |
| `test_pricing.py` | 16 | 100% |
| `test_factor_engine.py` | 18 | 100% |
| `test_backtest_detail.py` | 17 | 100% |
| `test_data_validator_detail.py` | 13 | 100% |
| `test_ic_compute_detail.py` | 14 | 100% |
| `test_engine_modules.py` | 19 | 100% |
| `test_cache.py` | 37 | 100% |
| `test_metrics.py` | 17 | 100% |
| `test_pricing.py` | 16 | 100% |
| `test_factor_engine.py` | 18 | 100% |
| `test_backtest_detail.py` | 17 | 100% |
| `test_data_validator_detail.py` | 13 | 100% |
| `test_ic_compute_detail.py` | 14 | 100% |

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

## Recent Updates (2026-09-11)

### Architecture Refactoring
- **New Modules**: Created `engine/recompute.py` (因子重算+IC分析), `engine/ic_scan.py` (IC计算), `ic_scan_utils.py` (扫描工具:清理/归档/大小扫描)
- **Split Detection Fix**: Rewrote `engine/pricing.py` `_detect_split_events()` to auto-scan all data — now correctly finds **5,551 split stocks** (was 0 due to hardcoded date pair)
- **Deleted Legacy Files**: Removed `high_winrate_stock_selection_v{3,4,5,6}.py` (4 files, 566 lines of dead code)
- **Script Modularization**: Extracted business logic from entry-point scripts into engine modules:
  - `run_full_recompute.py`: 365 → 19 lines
  - `factor_scan_mem_optimized.py`: 312 → 47 lines
  - `run_factor_ic_scan.py`: 279 → 31 lines

### Bug Fixes
- **Fixed**: `profit_factor` infinite return edge case in `engine/metrics.py` (no sells → returns 0)
- **Fixed**: `get_stock_prices()` DataFrame handling in `engine/pricing.py` (`xs()` may return DataFrame)
- **Fixed**: `DataValidator.apply_corrections()` requires prior `validate_all()` call; added dtype=float guard for pandas 3.x
- **Fixed**: Volume anomaly detection tests now use 20+ day windows (single-day spike absorbed by σ)
- **Fixed**: `compute_ic_session()` returns `factor_id` even when no daily IC (consistent API)

### Testing
- **Added**: 7 new test files (+130 tests) covering cache, metrics, pricing, factor engine, backtest detail, data validator detail, IC compute detail
- **Total**: 459 tests, 100% pass rate (17s)

### Documentation
- `AUDIT_REPORT_20260911.md`: Full audit report
- `CODE_QUALITY_CHECK_20260911.md`: Code quality findings
- `FACTOR_IC_ANALYSIS_REPORT.md`: IC analysis results
- `FULL_PIPELINE_REPORT.md`: Pipeline execution report
- `OPTIMIZATION_REPORT.md`: Performance optimization report

## Architecture Refactoring (2026-09-09)

### New Modules
- Created `engine/` (pricing, backtest, factor, metrics, cache) and `factors/` (factor_selector)
- **Refactored Scripts**: Reduced file sizes by 30-79% through modularization
  - `backtest_top10.py`: 388 → 178 lines (↓54%)
  - `high_winrate_stock_selection_v3.py`: 497 → 301 lines (↓39%)
  - `high_winrate_stock_selection_v4.py`: 484 → 87 lines (↓78%)
  - `high_winrate_stock_selection_v5.py`: 449 → 86 lines (↓79%)
  - `high_winrate_stock_selection_v6.py`: 456 → 92 lines (↓79%)
- **Logging System**: Added unified `logging_config.py` and integrated into all engine modules
- **Memory Cache**: Added `engine/cache.py` with LRU caching for data loading

### Bug Fixes
- **Fixed**: pandas DatetimeIndex empty check in `engine/backtest.py`
- **Fixed**: `nlargest()` API usage in tests
- **Improved**: Exception handling with specific error types in `engine/factor.py`

### Testing
- **Added**: 82 new tests covering engine modules and factor selection
- **Total**: 289 tests, 100% pass rate (at that time)
- **Coverage**: All core modules fully tested

### Documentation
- `ARCHITECTURE_REFACTOR.md`: Detailed architecture refactoring report
- `COMPREHENSIVE_REVIEW.md`: 9-dimension comprehensive review
- `FINAL_REVIEW_SUMMARY.md`: Final summary and action plan

## Previous Updates (2026-09-08)

- **Bug fixes**: Fixed int64 `LossySetitemError` in volume winsorize (`data_corrector.py`, `factor_rule_corrector.py`, `data_validator.py`)
- **Bug fixes**: Fixed `.iloc[0]` crash on scalar MultiIndex lookup (`data_corrector.py`)
- **Bug fixes**: Fixed key mismatch in `get_correction_recommendations()` (`trading_rules.py`)
- **Architecture**: Extracted `trading_rules_core.py` (pure rules, no pandas), `data_validator.py`, `ic_compute.py`, `memory_utils.py`
- **Tests**: Added 39 new tests; total 191, all passing
- **Security**: All hardcoded paths externalized via `config.py` / environment variables

## License

Internal use.
