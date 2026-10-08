#!/usr/bin/env python3
"""
每日 8 策略投票筛选入口
========================
执行全量 A 股（沪深）的 8 策略投票融合回测，输出 Top 20 并推送飞书。
用法:
    python scripts/screening_strategies.py
    python scripts/screening_strategies.py --top-n 20 --push-feishu
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import config as cfg
from engine.vote_fusion import run_signal_pipeline
from engine.backtest import BacktestEngine, create_backtest_engine
from engine.metrics import PerformanceAnalyzer
from feishu_notify import send_feishu


def run_single_screening(
    instrument: str,
    df: pd.DataFrame,
    backtest_engine: BacktestEngine,
    performance_analyzer: PerformanceAnalyzer,
) -> dict | None:
    """对单只股票运行 8 策略投票 + 回测"""
    try:
        stock = df.xs(instrument, level="instrument")
        if len(stock) < 100:
            return None

        # 信号生成
        result = run_signal_pipeline(stock, threshold=2, trend_filter=True)
        signals = result["signal"]

        # 向量化构造 price_map（避免逐行 .loc 循环）
        dates = stock.index.tolist()
        vals = stock[["$open", "$close", "$high", "$low"]].to_numpy()
        price_map = {
            (dates[i], instrument): {
                "open":  float(vals[i, 0]),
                "close": float(vals[i, 1]),
                "high":  float(vals[i, 2]),
                "low":   float(vals[i, 3]),
            }
            for i in range(len(dates))
        }

        # 构建买入信号字典
        signal_dict = {
            i: [instrument]
            for i, v in enumerate(signals.values)
            if v == 1
        }

        bt_result = backtest_engine.run(
            dates=dates,
            price_map=price_map,
            signals=signal_dict,
            hold_days=0,
            top_k=1,
        )
        metrics = performance_analyzer.analyze(bt_result.daily_value, bt_result.trades)
        return {
            "symbol":      instrument,
            "total_return": metrics.total_return_pct,
            "annual_return": metrics.annual_return_pct,
            "sharpe_ratio":  metrics.sharpe_ratio,
            "max_drawdown":  metrics.max_drawdown_pct,
            "win_rate":      metrics.win_rate_pct,
            "total_trades":  metrics.total_trades,
        }
    except Exception as e:
        print(f"  ⚠️ {instrument} 失败: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="8 策略投票筛选")
    parser.add_argument("--top-n", type=int, default=20, help="输出 Top N 结果")
    parser.add_argument("--push-feishu", action="store_true", help="推送飞书")
    parser.add_argument("--save-to-file", action="store_true", default=True, help="保存结果到文件")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  8 策略投票融合筛选  —  {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 加载全量数据
    print("📥 加载价格数据...")
    df = pd.read_parquet(cfg.DAILY_PV_FULL_PQ)
    df.index.names = ["datetime", "instrument"]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    # 提取全量股票列表（过滤北交所）
    all_instruments = df.index.get_level_values("instrument").drop_duplicates().tolist()
    instruments = [i for i in all_instruments if not i.startswith("BJ")]
    print(f"   共 {len(instruments)} 只股票\n")

    # 初始化回测引擎
    backtest_engine = create_backtest_engine()
    perf_analyzer = PerformanceAnalyzer(initial_capital=cfg.BACKTEST_INITIAL_CAPITAL)

    # 串行筛选（CPython GIL 使多线程反而更慢；~70 只/秒，全量 ~75s）
    results = []
    start = time.time()
    for i, inst in enumerate(instruments):
        r = run_single_screening(inst, df, backtest_engine, perf_analyzer)
        if r:
            results.append(r)
        if (i + 1) % 500 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            print(f"   进度: {i+1}/{len(instruments)} ({rate:.1f} 只/秒)")
    elapsed = time.time() - start
    print(f"\n✅ 筛选完成，有效结果 {len(results)} 只，耗时 {elapsed:.0f}s\n")

    if not results:
        print("⚠️ 无有效结果")
        return

    # 排序取 Top N
    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values("total_return", ascending=False).reset_index(drop=True)
    top_n = min(args.top_n, len(result_df))
    top_df = result_df.head(top_n)

    print(f"📊 Top {top_n} 收益率排名：")
    print(top_df[["symbol", "total_return", "sharpe_ratio", "max_drawdown", "win_rate"]].to_string(index=False))

    # 保存 Markdown 报告
    if args.save_to_file:
        out_path = Path(__file__).parent.parent / "筛选结果_策略投票.md"
        with open(out_path, "w") as f:
            f.write("# 8 策略投票融合筛选结果\n\n")
            f.write(f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}  |  有效股票：{len(results)} 只\n\n")
            f.write(top_df.to_markdown(index=False))
        print(f"\n💾 结果已保存：{out_path}")

    # 推送飞书
    if args.push_feishu:
        lines = [f"**8 策略投票筛选**  ({len(results)} 只有效)", ""]
        for idx, row in top_df.iterrows():
            lines.append(
                f"{idx+1}. **{row['symbol']}**  "
                f"收益{row['total_return']:+.1f}%  "
                f"夏普{row['sharpe_ratio']:.2f}  "
                f"回撤{row['max_drawdown']:.1f}%"
            )
        send_feishu("\n".join(lines))
        print("📱 飞书推送完成")


if __name__ == "__main__":
    main()
