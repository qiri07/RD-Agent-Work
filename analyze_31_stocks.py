#!/usr/bin/env python3
"""
31只标的因子分析与回测 — 精简高效版
=====================================
架构：使用 engine/ 模块
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path
import warnings, time
warnings.filterwarnings('ignore')

import config as cfg
from engine.pricing import PriceEngine
from engine.backtest import BacktestEngine, create_backtest_engine
from engine.factor import FactorEngine, create_factor_engine
from engine.metrics import PerformanceAnalyzer, create_performance_analyzer

logger = logging.getLogger(__name__)

# 目标股票
TARGET = {
    "SZ002532": "天山铝业", "SH601600": "中国铝业", "SH603558": "健盛集团",
    "SZ002170": "芭田股份", "SH603271": "永杰新材", "SZ002001": "新和成",
    "SZ002011": "盾安环境", "BJ920136": "永励精密", "SH603202": "天有为",
    "SZ002867": "周大生",   "SH605305": "中际联合", "BJ920208": "青矩技术",
    "BJ920735": "德源药业", "BJ920055": "隆源股份", "SZ002884": "凌霄泵业",
    "BJ920523": "德瑞锂电", "SH601702": "华峰铝业", "SH603551": "奥普科技",
    "SZ001395": "亚联机械", "BJ920029": "开发科技", "SZ300505": "川金诺",
    "SH603998": "方盛制药", "SZ300910": "瑞丰新材", "SH603298": "杭叉集团",
    "BJ920112": "巴兰仕",   "SZ300181": "佐力药业", "BJ920003": "中诚咨询",
    "SZ300446": "航天智造", "SH600600": "青岛啤酒", "BJ920107": "恒兴股份",
    "SZ002895": "川恒股份",
}
CODES = list(TARGET.keys())
N = len(CODES)

# 回测参数
ICAP = cfg.BACKTEST_INITIAL_CAPITAL
COMM = cfg.BACKTEST_COMMISSION_RATE
SLIP = cfg.BACKTEST_SLIPPAGE_RATE
MIN_TR = cfg.BACKTEST_MIN_TRADE_VALUE
HOLD = cfg.BACKTEST_HOLD_DAYS

# 拆分日期（自动检测）
_split_prev, _split_curr = cfg.get_split_dates()
SPLIT_PREV = pd.Timestamp(_split_prev) if _split_prev else pd.Timestamp("2026-09-01")
SPLIT_CURR = pd.Timestamp(_split_curr) if _split_curr else pd.Timestamp("2026-09-02")

WS = cfg.RDAGENT_WORKSPACE
SRC = cfg.FACTOR_SOURCE_DEBUG_CLEAN_H5

TOP_FIDS = [
    "02d7dce95b7f410aa3ba2f8c2ab29b57",
    "e380dae07ef8479f8523be67cdda0743",
    "705b5216b6864e8ab2b746740395b1a6",
    "3006ddb42efe4dc0b3e4470cf26e7155",
    "3f7b8bcf19d648029f385432c784e5dd",
    "0d44eee04fdc468b9b0d2ebe0195f8ad",
]


def main():
    t0 = time.time()
    logger.info("=" * 70)
    logger.info("  31只标的因子分析与回测")
    logger.info("=" * 70)

    # 初始化引擎
    price_engine = PriceEngine()
    backtest_engine = create_backtest_engine(
        initial_capital=ICAP,
        commission_rate=COMM,
        slippage_rate=SLIP,
        min_trade_value=MIN_TR
    )
    factor_engine = create_factor_engine(WS)
    perf_analyzer = create_performance_analyzer(ICAP)

    # ===== 1. 加载价格 =====
    logger.info("\n加载价格数据...")
    t1 = time.time()
    pv = pd.read_hdf(SRC, key='data')
    if pv.index.names == ['date', 'instrument']:
        pv.index = pv.index.set_names(['datetime', 'instrument'])
    pv = pv.sort_index()[~pv.index.duplicated(keep='first')]

    # 复权
    pv, split_stocks = price_engine.compute_adjusted_prices(pv)
    logger.info("  复权调整: %d 只股票发生拆分", len(split_stocks))

    prices = pv[['$open', '$close']].to_numpy()
    date_idx = pv.index.get_level_values('datetime').unique()
    date_map = {d: i for i, d in enumerate(sorted(date_idx))}
    valid_dates = [d for d in date_map if d < SPLIT_CURR]
    VDATES = [date_map[d] for d in valid_dates]
    logger.info("  %d行 loaded in %.1fs, %d trading days", len(pv), time.time()-t1, len(valid_dates))

    # 构建快速查找
    inst_to_idx = {code: i for i, code in enumerate(CODES)}
    stock_date_idx = {}
    for si, code in enumerate(CODES):
        rows = pv.xs(code, level=1)[['$open', '$close']]
        rows = rows[rows.index < SPLIT_CURR].sort_index()
        if len(rows) < 5:
            continue
        stock_date_idx[si] = [(date_map.get(d, -1), rows.loc[d, '$close']) for d in rows.index if d in date_map]

    # ===== 2. 加载因子 =====
    logger.info("\n加载因子得分...")
    t1 = time.time()
    factor_data = factor_engine.load_factors(TOP_FIDS)
    logger.info("  因子加载完成 in %.1fs, %d factors", time.time()-t1, len(factor_data))

    # ===== 3. 单只股票表现 =====
    print_analyze_individual_performance(stock_date_idx, TARGET, valid_dates, CODES)

    # ===== 4. 等权买入持有31只 =====
    logger.info("\n" + "=" * 70)
    logger.info("  策略1: 等权买入持有31只股票")
    logger.info("=" * 70)
    hold_result = run_equal_weight_hold(
        valid_dates, stock_date_idx, CODES, backtest_engine
    )
    hold_metrics = perf_analyzer.analyze(hold_result['daily_value'], hold_result['trades'])
    logger.info("\n%s", perf_analyzer.generate_report(hold_metrics, "策略1: 等权买入持有").strip())
    save_results('backtest_31_hold', hold_result)

    # ===== 5. 因子轮动回测 =====
    logger.info("\n" + "=" * 70)
    logger.info("  策略2: 多因子轮动(Top10, 5日持仓)")
    logger.info("=" * 70)
    rotation_result = run_factor_rotation(
        valid_dates, stock_date_idx, CODES, factor_data, backtest_engine
    )
    rotation_metrics = perf_analyzer.analyze(rotation_result['daily_value'], rotation_result['trades'])
    logger.info("\n%s", perf_analyzer.generate_report(rotation_metrics, "策略2: 因子轮动").strip())
    save_results('backtest_31_rotation', rotation_result)

    # ===== 6. 因子IC分析 =====
    logger.info("\n" + "=" * 70)
    logger.info("  因子IC分析（目标股票池）")
    logger.info("=" * 70)
    analyze_factor_ic(factor_data, stock_date_idx, CODES, valid_dates, HOLD)

    # ===== 7. 汇总 =====
    print_summary(hold_metrics, rotation_metrics)

    elapsed = time.time() - t0
    logger.info("\n总耗时: %.1fs", elapsed)
    logger.info("=" * 70)


def print_analyze_individual_performance(stock_date_idx, TARGET, valid_dates, CODES):
    """打印单只股票表现"""
    logger.info("\n" + "=" * 70)
    logger.info("  单只股票买入持有表现")
    logger.info("=" * 70)
    perf = []
    for si, code in enumerate(CODES):
        if si not in stock_date_idx:
            continue
        entries = stock_date_idx[si]
        if len(entries) < 5:
            continue
        first_close = entries[0][1]
        last_close = entries[-1][1]
        if first_close <= 0 or last_close <= 0:
            continue
        ret = (last_close / first_close - 1) * 100
        days = (entries[-1][0] - entries[0][0])
        yrs = days / 365.25
        ann = ((last_close / first_close) ** (1/max(yrs,0.01)) - 1) * 100 if yrs > 0 else ret
        cum = np.array([e[1] for e in entries]) / first_close
        dd = ((cum / np.maximum.accumulate(cum) - 1)).min() * 100
        perf.append({
            'code': code, 'name': TARGET[code],
            'return': round(ret, 2), 'ann_return': round(ann, 2),
            'max_dd': round(dd, 2),
            'start': str(valid_dates[entries[0][0]].date()) if entries[0][0] < len(valid_dates) else '?',
            'end': str(valid_dates[entries[-1][0]].date()) if entries[-1][0] < len(valid_dates) else '?',
        })

    perf_df = pd.DataFrame(perf).sort_values('return', ascending=False)
    logger.info("\n  %10s  %8s  %8s  %8s  %8s  %s", "代码", "名称", "总收益%", "年化%", "回撤%", "区间")
    logger.info("  %10s  %8s  %8s  %8s  %8s  %s", "-"*10, "-"*8, "-"*8, "-"*8, "-"*8, "-"*20)
    for _, r in perf_df.iterrows():
        s = "+" if r['return'] >= 0 else ""
        logger.info("  %10s  %8s  %s%6.2f%%  %s%6.2f%%  %s%6.2f%%  %s~%s",
                    r['code'], r['name'], s, r['return'], s, r['ann_return'], s, r['max_dd'], r['start'], r['end'])


def run_equal_weight_hold(valid_dates, stock_date_idx, CODES, engine):
    """运行等权买入持有策略"""
    stock_first = {}
    for si, code in enumerate(CODES):
        if si in stock_date_idx and stock_date_idx[si]:
            stock_first[si] = stock_date_idx[si][0][0]
    if not stock_first:
        logger.warning("无有效数据")
        return {'daily_value': [], 'trades': []}

    start_idx = max(stock_first.values())

    price_map = {}
    for si, code in enumerate(CODES):
        if si not in stock_date_idx:
            continue
        for di, close in stock_date_idx[si]:
            if di < len(valid_dates):
                price_map[(valid_dates[di], code)] = {'open': close, 'close': close}

    target_stocks = list(stock_first.keys())
    result = engine.run_fixed_hold(valid_dates, price_map, target_stocks, hold_days=0)
    return {'daily_value': result.daily_value, 'trades': result.trades}


def run_factor_rotation(valid_dates, stock_date_idx, CODES, factor_data, engine):
    """运行因子轮动策略"""
    stock_factor_matrix = {}
    for fid, fdf in factor_data.items():
        stock_factor_matrix[fid] = {}
        for si, code in enumerate(CODES):
            try:
                vals = fdf.loc[:, code]
                vals = vals[np.isfinite(vals)].ffill().fillna(0)
                stock_factor_matrix[fid][si] = vals
            except Exception:
                stock_factor_matrix[fid][si] = None

    composite_scores = {}
    for di in range(len(valid_dates)):
        d = valid_dates[di]
        scores = {}
        for si in range(len(CODES)):
            vals = []
            for fid in factor_data:
                if si in stock_factor_matrix.get(fid, {}) and stock_factor_matrix[fid][si] is not None:
                    try:
                        v = stock_factor_matrix[fid][si].loc[d]
                        if np.isfinite(v):
                            vals.append(v)
                    except Exception:
                        pass
            if vals:
                scores[si] = np.mean(vals)
        if scores:
            arr = np.array(list(scores.values()))
            mean_v = arr.mean()
            std_v = arr.std() if arr.std() > 0 else 1
            composite_scores[di] = {si: (v - mean_v) / std_v for si, v in scores.items()}

    signals = {}
    for di, scores in composite_scores.items():
        target_scores = {si: v for si, v in scores.items() if si < len(CODES)}
        if len(target_scores) >= 10:
            selected = sorted(target_scores, key=target_scores.get, reverse=True)[:10]
            signals[di] = [CODES[si] for si in selected]

    price_map = {}
    for si, code in enumerate(CODES):
        if si in stock_date_idx:
            for di, close in stock_date_idx[si]:
                if di < len(valid_dates):
                    price_map[(valid_dates[di], code)] = {'open': close, 'close': close}

    result = engine.run(valid_dates, price_map, signals, hold_days=5, top_k=10)
    return {'daily_value': result.daily_value, 'trades': result.trades}


def analyze_factor_ic(factor_data, stock_date_idx, CODES, valid_dates, hold_days):
    """分析因子IC"""
    ic_results = []
    for fid in factor_data:
        ics = []
        for di, d in enumerate(valid_dates[:-hold_days]):
            fvals = {}
            frvals = {}
            for si, code in enumerate(CODES):
                try:
                    fv = factor_data[fid].loc[d, code]
                    if not np.isfinite(fv):
                        continue
                    fvals[si] = fv
                    fwd_entries = [(e[0], e[1]) for e in stock_date_idx[si] if e[0] > di]
                    if not fwd_entries:
                        continue
                    fwd_d = min(fwd_entries, key=lambda x: abs(x[0] - (di + hold_days)))
                    if fwd_d[0] >= len(valid_dates):
                        continue
                    p1 = next((e[1] for e in stock_date_idx[si] if e[0] == di), None)
                    p2 = next((e[1] for e in stock_date_idx[si] if e[0] == fwd_d[0]), None)
                    if p1 and p1 > 0 and p2 and p2 > 0:
                        frvals[si] = (p2 / p1 - 1) * 100
                except Exception:
                    continue
            if len(fvals) < 5 or len(frvals) < 5:
                continue
            common_si = set(fvals.keys()) & set(frvals.keys())
            if len(common_si) < 5:
                continue
            f_arr = np.array([fvals[s] for s in common_si])
            r_arr = np.array([frvals[s] for s in common_si])
            if np.std(f_arr) > 0 and np.std(r_arr) > 0:
                ic = np.corrcoef(f_arr, r_arr)[0, 1]
                if np.isfinite(ic):
                    ics.append(ic)
        if ics:
            arr = np.array(ics)
            ic_results.append({
                'fid': fid,
                'mean_ic': float(np.mean(arr)),
                'abs_mean': float(np.mean(np.abs(arr))),
                'ir': float(np.mean(arr) / np.std(arr)) if np.std(arr) > 0 else 0,
                'pos_ratio': float(np.mean(arr > 0)),
                'n_days': len(ics),
            })

    ic_results.sort(key=lambda x: abs(x['mean_ic']), reverse=True)
    logger.info("\n  %3s  %20s  %8s  %8s  %6s  %7s  %5s", "排名", "因子ID", "IC均值", "|IC|均值", "IR", "正向%", "天数")
    logger.info("  %3s  %20s  %8s  %8s  %6s  %7s  %5s", "---", "--------------------", "--------", "--------", "------", "-------", "-----")
    for rank, r in enumerate(ic_results[:10], 1):
        logger.info("  %3d  %20s  %+7.4f  %7.4f  %6.3f  %6.0f%%  %5d",
                    rank, r['fid'], r['mean_ic'], r['abs_mean'], r['ir'], r['pos_ratio']*100, r['n_days'])


def print_summary(hold_metrics, rotation_metrics):
    """打印汇总"""
    logger.info("\n" + "=" * 70)
    logger.info("  策略对比汇总")
    logger.info("=" * 70)
    logger.info("  %-30s  %10s  %10s  %8s  %10s", "策略", "总收益%", "年化%", "夏普", "回撤%")
    logger.info("  %30s  %10s  %10s  %8s  %10s", "-"*30, "-"*10, "-"*10, "-"*8, "-"*10)
    logger.info("  %-30s  %+.9f%%  %+.9f%%  %8.3f  %+.9f%%",
                "等权买入持有(31只)",
                hold_metrics.total_return_pct, hold_metrics.annual_return_pct,
                hold_metrics.sharpe_ratio, hold_metrics.max_drawdown_pct)
    logger.info("  %-30s  %+.9f%%  %+.9f%%  %8.3f  %+.9f%%",
                "因子轮动(Top10,5日)",
                rotation_metrics.total_return_pct, rotation_metrics.annual_return_pct,
                rotation_metrics.sharpe_ratio, rotation_metrics.max_drawdown_pct)


def save_results(prefix, result):
    """保存结果"""
    df = pd.DataFrame(result['daily_value'])
    if not df.empty:
        df.set_index('date')['value'].to_csv(f'{prefix}_nav.csv')
    pd.DataFrame(result['trades']).to_csv(f'{prefix}_trades.csv', index=False)


if __name__ == "__main__":
    main()
