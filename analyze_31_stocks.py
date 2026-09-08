#!/usr/bin/env python3
"""
31只标的因子分析与回测 — 精简高效版
=====================================
"""
import pandas as pd
import numpy as np
from pathlib import Path
import warnings, time
warnings.filterwarnings('ignore')

import config as cfg

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

ICAP = cfg.BACKTEST_INITIAL_CAPITAL
COMM = cfg.BACKTEST_COMMISSION_RATE
SLIP = cfg.BACKTEST_SLIPPAGE_RATE
MIN_TR = cfg.BACKTEST_MIN_TRADE_VALUE
HOLD = cfg.BACKTEST_HOLD_DAYS
SPLIT_CURR = pd.Timestamp(cfg.BACKTEST_SPLIT_DATE_CURR or "2026-09-02")
SPLIT_PREV = pd.Timestamp(cfg.BACKTEST_SPLIT_DATE_PREV or "2026-09-01")
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
    print("=" * 70)
    print("  31只标的因子分析与回测")
    print("=" * 70)

    # ===== 1. 加载价格 =====
    print("\n📂 加载价格数据...")
    t1 = time.time()
    pv = pd.read_hdf(SRC, key='data')
    if pv.index.names == ['date', 'instrument']:
        pv.index = pv.index.set_names(['datetime', 'instrument'])
    pv = pv.sort_index()[~pv.index.duplicated(keep='first')]

    # 复权
    try:
        pc_prev = pv.xs(SPLIT_PREV, level='datetime')['$close']
        pc_curr = pv.xs(SPLIT_CURR, level='datetime')['$close']
    except KeyError:
        pass
    else:
        common = pc_prev.index.intersection(pc_curr.index)
        ratios = pc_prev[common] / pc_curr[common]
        splits = ratios[ratios > 3.0].index.tolist()
        adj = pv.copy()
        mask = pv.index.get_level_values('datetime') < SPLIT_CURR
        for stock in splits:
            sm = mask & (pv.index.get_level_values('instrument') == stock)
            r = ratios[stock]
            for col in ['$open', '$close', '$high', '$low']:
                adj.loc[sm, col] = pv.loc[sm, col] * r
        pv = adj

    prices = pv[['$open', '$close']].to_numpy()
    date_idx = pv.index.get_level_values('datetime').unique()
    date_map = {d: i for i, d in enumerate(sorted(date_idx))}
    valid_dates = [d for d in date_map if d < SPLIT_CURR]
    VDATES = [date_map[d] for d in valid_dates]
    print(f"  {len(pv):,}行 loaded in {time.time()-t1:.1f}s, {len(valid_dates)} trading days")

    # 构建快速查找: (date_idx, stock_idx) -> price
    inst_to_idx = {code: i for i, code in enumerate(CODES)}
    # 对每只股票，找其在价格数组中的行号范围
    stock_date_idx = {}  # stock_idx -> sorted list of (global_date_idx, close_price)
    for si, code in enumerate(CODES):
        rows = pv.xs(code, level=1)[['$open', '$close']]
        rows = rows[rows.index < SPLIT_CURR].sort_index()
        if len(rows) < 5:
            continue
        stock_date_idx[si] = [(date_map.get(d, -1), rows.loc[d, '$close']) for d in rows.index if d in date_map]

    # ===== 2. 加载因子 =====
    print("\n📂 加载因子得分...")
    t1 = time.time()
    factor_data = {}
    for fid in TOP_FIDS:
        h5 = WS / fid / "result.h5"
        if not h5.exists():
            continue
        try:
            df = pd.read_hdf(h5, key="data")
            fname = df.columns[0]
            df = df.rename(columns={fname: fid})
            idx = df.index
            if idx.names == ["instrument", "date"]:
                df.index = pd.MultiIndex.from_tuples([(t[1], t[0]) for t in idx], names=["datetime", "instrument"])
            elif idx.names == [None, None]:
                first = idx[0]
                if isinstance(first[0], str) and first[0].startswith(("SH","SZ","BJ")):
                    df.index = pd.MultiIndex.from_tuples([(t[1], t[0]) for t in idx], names=["datetime", "instrument"])
                else:
                    df.index.names = ["datetime", "instrument"]
            elif idx.names[0] != "datetime":
                df.index.names = ["datetime", "instrument"]
            df = df.ffill().fillna(0)[~df.index.duplicated(keep='first')]
            factor_data[fid] = df[fid]
        except Exception as e:
            print(f"  加载 {fid} 失败: {e}")

    print(f"  因子加载完成 in {time.time()-t1:.1f}s, {len(factor_data)} factors")

    # ===== 3. 单只股票表现 =====
    print("\n" + "=" * 70)
    print("  一、单只股票买入持有表现")
    print("=" * 70)
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
    print(f"\n  {'代码':>10}  {'名称':>8}  {'总收益%':>8}  {'年化%':>8}  {'回撤%':>8}  {'区间'}")
    print(f"  {'─'*10}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*20}")
    for _, r in perf_df.iterrows():
        s = "+" if r['return'] >= 0 else ""
        print(f"  {r['code']:>10}  {r['name']:>8}  {s}{r['return']:>6.2f}%  {s}{r['ann_return']:>6.2f}%  "
              f"{r['max_dd']:>+7.2f}%  {r['start']}~{r['end']}")

    # ===== 4. 等权买入持有31只 =====
    print("\n" + "=" * 70)
    print("  二、策略1: 等权买入持有31只股票")
    print("=" * 70)

    # 找每只股票的起始日期索引
    stock_first = {}
    for si, code in enumerate(CODES):
        if si in stock_date_idx and stock_date_idx[si]:
            stock_first[si] = stock_date_idx[si][0][0]
    if not stock_first:
        print("  无有效数据")
        return
    start_idx = max(stock_first.values())

    alloc_per = ICAP / N
    cash = ICAP
    positions = {}  # si -> {'shares': n, 'entry_price': p, 'entry_idx': i}
    daily_nav = []
    trades = []

    for di, d in enumerate(valid_dates):
        if di < start_idx:
            continue
        if di == start_idx:
            # 建仓
            for si in stock_first:
                entries = stock_date_idx[si]
                # 找到di对应的条目
                row_idx = None
                for e_di, e_close in entries:
                    if e_di == di:
                        row_idx = e_di
                        bp = e_close
                        break
                if row_idx is None or bp <= 0:
                    continue
                inv = alloc_per * 0.99
                if inv < MIN_TR:
                    continue
                shares = int(inv / bp / 100) * 100
                if shares <= 0:
                    continue
                cost = shares * bp * (1 + COMM + SLIP)
                if cost > cash:
                    shares = int(cash / bp / 100) * 100
                    if shares <= 0:
                        continue
                    cost = shares * bp * (1 + COMM + SLIP)
                cash -= cost
                positions[si] = {'shares': shares, 'price': bp, 'idx': di}
                trades.append({'date': d, 'action': 'BUY', 'stock': CODES[si], 'shares': shares, 'price': bp})
            total = cash + sum(positions[si]['shares'] * 
                              next((e[1] for e in stock_date_idx[si] if e[0] == di), 0)
                              for si in positions)
            daily_nav.append({'date': d, 'value': total})
            continue

        # 每日净值
        total = cash
        for si in list(positions.keys()):
            entry = next((e[1] for e in stock_date_idx[si] if e[0] == di), None)
            if entry:
                total += positions[si]['shares'] * entry
        daily_nav.append({'date': d, 'value': total})

    # 最后平仓
    last_d = valid_dates[-1]
    last_di = len(valid_dates) - 1
    final_val = cash
    for si, pos in positions.items():
        entry = next((e[1] for e in stock_date_idx[si] if e[0] == last_di), None)
        if entry:
            sp = entry * (1 - COMM - SLIP)
            tv = pos['shares'] * sp
            final_val += tv
            trades.append({'date': last_d, 'action': 'SELL', 'stock': CODES[si],
                           'shares': pos['shares'], 'price': entry,
                           'pnl_pct': (entry / pos['price'] - 1) * 100})

    nav = pd.Series([v['value'] for v in daily_nav], index=[v['date'] for v in daily_nav]) / ICAP
    tr = (nav.iloc[-1] - 1) * 100
    dy = (nav.index[-1] - nav.index[0]).days / 365.25
    ar = (nav.iloc[-1] ** (1/dy) - 1) * 100 if dy > 0 else tr
    dr = nav.pct_change().dropna()
    sh = (dr.mean() * 252 - 0.02) / (dr.std() * np.sqrt(252)) if dr.std() > 0 else 0
    mdd = (nav / nav.cummax() - 1).min() * 100
    sells = [t for t in trades if t['action'] == 'SELL']
    wins = [t for t in sells if t.get('pnl_pct', 0) > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0

    print(f"  区间: {nav.index[0].date()} ~ {nav.index[-1].date()} ({len(nav)}天)")
    print(f"  总收益: {tr:+.2f}%  年化: {ar:+.2f}%  夏普: {sh:.3f}")
    print(f"  最大回撤: {mdd:.2f}%  胜率: {wr:.1f}%")
    print(f"  最终净值: {nav.iloc[-1]:.4f}  ({nav.iloc[-1]*ICAP:,.0f}元)")

    # ===== 5. 因子轮动回测 =====
    print("\n" + "=" * 70)
    print("  三、策略2: 多因子轮动(Top10, 5日持仓)")
    print("=" * 70)

    # 预计算每日因子得分（标准化后合成）
    print("  计算因子合成得分...")
    t1 = time.time()
    # 提取每只股票在每只因子上的得分时间序列
    stock_factor_matrix = {}  # {fid: {si: [val_at_each_date]}}
    for fid, fdf in factor_data.items():
        stock_factor_matrix[fid] = {}
        for si, code in enumerate(CODES):
            try:
                vals = fdf.loc[:, code]
                vals = vals[np.isfinite(vals)].ffill().fillna(0)
                stock_factor_matrix[fid][si] = vals
            except Exception:
                stock_factor_matrix[fid][si] = None

    # 对于每个日期，计算横截面标准化后合成
    composite_scores = {}  # date_idx -> {si: composite_score}
    for di in range(len(valid_dates)):
        d = valid_dates[di]
        scores = {}
        for si in range(N):
            # 取该日所有因子的均值作为综合得分
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

    print(f"  因子得分计算完成 in {time.time()-t1:.1f}s")

    # 轮动回测
    cash = ICAP
    positions = {}
    pending = {}
    daily_nav2 = []
    trades2 = []

    for di, d in enumerate(valid_dates):
        # 到期卖出
        to_sell = [si for si, pi in pending.items() if pi <= di]
        for si in to_sell:
            if si in positions:
                entry = next((e[1] for e in stock_date_idx[si] if e[0] == di), None)
                if entry and entry > 0:
                    sp = entry * (1 - COMM - SLIP)
                    tv = positions[si]['shares'] * sp
                    cash += tv
                    trades2.append({'date': d, 'action': 'SELL', 'stock': CODES[si],
                                    'shares': positions[si]['shares'], 'price': entry,
                                    'pnl_pct': (entry / positions[si]['price'] - 1) * 100})
                del positions[si]
        for si in to_sell:
            pending.pop(si, None)

        # 净值
        total = cash
        for si, pos in positions.items():
            entry = next((e[1] for e in stock_date_idx[si] if e[0] == di), None)
            if entry:
                total += pos['shares'] * entry
        daily_nav2.append({'date': d, 'value': total})

        # 选股(T-1)
        if di == 0:
            continue
        prev_di = di - 1
        if prev_di not in composite_scores:
            continue
        scores = composite_scores[prev_di]
        # 只选目标股票
        target_scores = {si: v for si, v in scores.items() if si < N}
        if len(target_scores) < 10:
            continue
        selected = set(sorted(target_scores, key=target_scores.get, reverse=True)[:10])

        # 调仓
        for si in list(positions.keys()):
            if si not in selected:
                entry = next((e[1] for e in stock_date_idx[si] if e[0] == di), None)
                if entry and entry > 0:
                    sp = entry * (1 - COMM - SLIP)
                    tv = positions[si]['shares'] * sp
                    cash += tv
                    trades2.append({'date': d, 'action': 'SELL', 'stock': CODES[si],
                                    'shares': positions[si]['shares'], 'price': entry,
                                    'pnl_pct': (entry / positions[si]['price'] - 1) * 100})
                del positions[si]

        alloc = total / 10
        for si in selected:
            if si in positions:
                continue
            entry = next((e for e in stock_date_idx[si] if e[0] == di), None)
            if entry is None or entry[1] <= 0:
                continue
            bp = entry[1]
            inv = min(alloc, cash * 0.99)
            if inv < MIN_TR:
                continue
            shares = int(inv / bp / 100) * 100
            if shares <= 0:
                continue
            cost = shares * bp * (1 + COMM + SLIP)
            if cost > cash:
                shares = int(cash / bp / 100) * 100
                if shares <= 0:
                    continue
                cost = shares * bp * (1 + COMM + SLIP)
            cash -= cost
            positions[si] = {'shares': shares, 'price': bp}
            trades2.append({'date': d, 'action': 'BUY', 'stock': CODES[si],
                            'shares': shares, 'price': bp})
            if HOLD > 0 and di + HOLD < len(valid_dates):
                pending[si] = di + HOLD

    # 最后平仓
    last_di = len(valid_dates) - 1
    for si in list(positions.keys()):
        entry = next((e[1] for e in stock_date_idx[si] if e[0] == last_di), None)
        if entry:
            sp = entry * (1 - COMM - SLIP)
            cash += positions[si]['shares'] * sp
            trades2.append({'date': valid_dates[last_di], 'action': 'SELL', 'stock': CODES[si],
                            'shares': positions[si]['shares'], 'price': entry,
                            'pnl_pct': (entry / positions[si]['price'] - 1) * 100})

    nav2 = pd.Series([v['value'] for v in daily_nav2], index=[v['date'] for v in daily_nav2]) / ICAP
    tr2 = (nav2.iloc[-1] - 1) * 100
    dy2 = (nav2.index[-1] - nav2.index[0]).days / 365.25
    ar2 = (nav2.iloc[-1] ** (1/max(dy2,0.01)) - 1) * 100 if dy2 > 0 else tr2
    dr2 = nav2.pct_change().dropna()
    sh2 = (dr2.mean() * 252 - 0.02) / (dr2.std() * np.sqrt(252)) if dr2.std() > 0 else 0
    mdd2 = (nav2 / nav2.cummax() - 1).min() * 100
    sells2 = [t for t in trades2 if t['action'] == 'SELL']
    wins2 = [t for t in sells2 if t.get('pnl_pct', 0) > 0]
    wr2 = len(wins2) / len(sells2) * 100 if sells2 else 0

    print(f"  区间: {nav2.index[0].date()} ~ {nav2.index[-1].date()} ({len(nav2)}天)")
    print(f"  总收益: {tr2:+.2f}%  年化: {ar2:+.2f}%  夏普: {sh2:.3f}")
    print(f"  最大回撤: {mdd2:.2f}%  胜率: {wr2:.1f}%")
    print(f"  最终净值: {nav2.iloc[-1]:.4f}  ({nav2.iloc[-1]*ICAP:,.0f}元)")

    # ===== 6. 因子IC分析 =====
    print("\n" + "=" * 70)
    print("  四、因子IC分析（目标股票池）")
    print("=" * 70)

    # 对每个因子，计算与未来收益的IC
    ic_results = []
    for fid in factor_data:
        ics = []
        for di, d in enumerate(valid_dates[:-HOLD]):
            # 当前因子值（仅目标股票）
            fvals = {}
            frvals = {}
            for si, code in enumerate(CODES):
                try:
                    fv = factor_data[fid].loc[d, code]
                    if not np.isfinite(fv):
                        continue
                    fvals[si] = fv
                    # 向前收益
                    fwd_entries = [(e[0], e[1]) for e in stock_date_idx[si] if e[0] > di]
                    if not fwd_entries:
                        continue
                    fwd_d = min(fwd_entries, key=lambda x: abs(x[0] - (di + HOLD)))
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
    print(f"  {'排名':>3}  {'因子ID':>20}  {'IC均值':>8}  {'|IC|均值':>8}  {'IR':>6}  {'正向%':>7}  {'天数':>5}")
    print(f"  {'─'*3}  {'─'*20}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*7}  {'─'*5}")
    for rank, r in enumerate(ic_results[:10], 1):
        print(f"  {rank:>3}  {r['fid']:>20}  {r['mean_ic']:>+7.4f}  {r['abs_mean']:>7.4f}  "
              f"{r['ir']:>6.3f}  {r['pos_ratio']:>6.0%}  {r['n_days']:>5}")

    # ===== 7. 汇总 =====
    print(f"\n{'='*70}")
    print("  五、策略对比汇总")
    print(f"{'='*70}")
    print(f"  {'策略':<30}  {'总收益%':>10}  {'年化%':>10}  {'夏普':>8}  {'回撤%':>10}")
    print(f"  {'─'*30}  {'─'*10}  {'─'*10}  {'─'*8}  {'─'*10}")
    print(f"  {'等权买入持有(31只)':<30}  {tr:+>9.2f}%  {ar:+>9.2f}%  {sh:>8.3f}  {mdd:>+9.2f}%")
    print(f"  {'因子轮动(Top10,5日)':<30}  {tr2:+>9.2f}%  {ar2:+>9.2f}%  {sh2:>8.3f}  {mdd2:>+9.2f}%")

    # 保存
    nav.to_csv('backtest_31_hold_nav.csv')
    nav2.to_csv('backtest_31_rotation_nav.csv')
    pd.DataFrame(trades).to_csv('backtest_31_hold_trades.csv', index=False)
    pd.DataFrame(trades2).to_csv('backtest_31_rotation_trades.csv', index=False)
    pd.DataFrame(perf).to_csv('backtest_31_individual_perf.csv', index=False)

    elapsed = time.time() - t0
    print(f"\n  ⏱️  总耗时: {elapsed:.1f}s")
    print(f"  💾 已保存: backtest_31_*.csv")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
