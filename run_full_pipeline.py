#!/usr/bin/env python3
"""
完整因子分析流水线
==================
流程: 因子计算 → IC分析 → 选股 → 回测 → 绩效评估 → 飞书推送

用法:
    python3 run_full_pipeline.py                    # 完整流程
    python3 run_full_pipeline.py --phase ic-only    # 只跑 IC 分析
    python3 run_full_pipeline.py --phase backtest   # 只跑回测
    python3 run_full_pipeline.py --dry-run          # 只检查不执行
"""
import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from feishu_notify import send_combined_report

logger = logging.getLogger(__name__)


def log(msg: str):
    """打印带时间戳的日志"""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)
    logger.info(msg)


def phase_recompute_factors(dry_run: bool = False) -> bool:
    """Phase 1: 因子重算"""
    log("\n" + "=" * 70)
    log("  Phase 1: 因子重算")
    log("=" * 70)
    
    if dry_run:
        log("  [DRY RUN] 跳过因子重算")
        return True
    
    cmd = [sys.executable, "batch_recompute_factors.py", "--phase2"]
    result = subprocess.run(cmd, cwd=str(cfg.PROJECT_ROOT))
    return result.returncode == 0


def phase_ic_analysis(feishu_url: str = None) -> pd.DataFrame:
    """Phase 2: IC 分析"""
    log("\n" + "=" * 70)
    log("  Phase 2: IC 分析")
    log("=" * 70)
    
    cmd = [sys.executable, "run_ic_fast.py"]
    if feishu_url:
        cmd.extend(["--feishu-url", feishu_url])
    
    result = subprocess.run(cmd, cwd=str(cfg.PROJECT_ROOT))
    
    # 读取 IC 结果
    ic_csv = cfg.PROJECT_ROOT / "ic_scan_results_new.csv"
    if ic_csv.exists():
        return pd.read_csv(ic_csv)
    return pd.DataFrame()


def phase_stock_selection(ic_df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Phase 3: 选股"""
    log("\n" + "=" * 70)
    log(f"  Phase 3: 选股 (Top {top_n} 因子)")
    log("=" * 70)
    
    cmd = [sys.executable, "run_pipeline.py", "--stocks-only", "--top-n", str(top_n)]
    result = subprocess.run(cmd, cwd=str(cfg.PROJECT_ROOT))
    
    # 读取选股结果
    stocks_csv = cfg.PROJECT_ROOT / "top10_stocks_new.csv"
    if stocks_csv.exists():
        return pd.read_csv(stocks_csv)
    return pd.DataFrame()


def phase_backtest() -> dict:
    """Phase 4: 回测"""
    log("\n" + "=" * 70)
    log("  Phase 4: 回测")
    log("=" * 70)
    
    cmd = [sys.executable, "backtest_top10.py"]
    result = subprocess.run(cmd, cwd=str(cfg.PROJECT_ROOT))
    
    # 读取回测结果
    nav_csv = cfg.PROJECT_ROOT / "backtest_nav.csv"
    trades_csv = cfg.PROJECT_ROOT / "backtest_trades.csv"
    
    metrics = {}
    if nav_csv.exists():
        nav_df = pd.read_csv(nav_csv)
        if not nav_df.empty:
            metrics['initial_value'] = nav_df['value'].iloc[0] if 'value' in nav_df.columns else 0
            metrics['final_value'] = nav_df['value'].iloc[-1] if 'value' in nav_df.columns else 0
            metrics['total_return'] = (metrics['final_value'] / max(metrics['initial_value'], 1) - 1) * 100
    
    if trades_csv.exists():
        trades_df = pd.read_csv(trades_csv)
        metrics['total_trades'] = len(trades_df)
    
    return metrics


def phase_performance_evaluation(backtest_metrics: dict) -> dict:
    """Phase 5: 绩效评估"""
    log("\n" + "=" * 70)
    log("  Phase 5: 绩效评估")
    log("=" * 70)
    
    from engine.metrics import PerformanceAnalyzer
    
    nav_csv = cfg.PROJECT_ROOT / "backtest_nav.csv"
    trades_csv = cfg.PROJECT_ROOT / "backtest_trades.csv"
    
    if not nav_csv.exists():
        log("  ⚠️  回测结果不存在，跳过绩效评估")
        return {}
    
    analyzer = PerformanceAnalyzer(initial_capital=cfg.BACKTEST_INITIAL_CAPITAL)
    
    # 读取回测数据
    nav_df = pd.read_csv(nav_csv)
    trades_df = pd.read_csv(trades_csv) if trades_csv.exists() else pd.DataFrame()
    
    daily_value = nav_df.to_dict('records')
    trades = trades_df.to_dict('records') if not trades_df.empty else []
    
    # 计算绩效指标
    metrics = analyzer.analyze(daily_value, trades)
    
    log(f"\n  📊 绩效指标:")
    log(f"     初始净值: {metrics.final_nav / (1 + metrics.total_return_pct/100):.4f}" if metrics.total_return_pct else f"     初始净值: 1.0000")
    log(f"     最终净值: {metrics.final_nav:.4f}")
    log(f"     总收益率: {metrics.total_return_pct:+.2f}%")
    log(f"     年化收益率: {metrics.annual_return_pct:+.2f}%")
    log(f"     夏普比率: {metrics.sharpe_ratio:.3f}")
    log(f"     最大回撤: {metrics.max_drawdown_pct:.2f}%")
    log(f"     胜率: {metrics.win_rate_pct:.1f}%")
    log(f"     总交易次数: {metrics.total_trades}")
    
    return {
        'total_return': metrics.total_return_pct,
        'annual_return': metrics.annual_return_pct,
        'sharpe': metrics.sharpe_ratio,
        'max_drawdown': metrics.max_drawdown_pct,
        'win_rate': metrics.win_rate_pct,
        'final_nav': metrics.final_nav
    }


def phase_feishu_push(ic_df: pd.DataFrame, stocks_df: pd.DataFrame, 
                      perf_metrics: dict, feishu_url: str = None) -> bool:
    """Phase 6: 飞书推送"""
    log("\n" + "=" * 70)
    log("  Phase 6: 飞书推送")
    log("=" * 70)
    
    if feishu_url:
        import feishu_notify
        feishu_notify.FEISHU_WEBHOOK_URL = feishu_url
    
    try:
        success = send_combined_report(ic_df, stocks_df, top_n=10)
        if success:
            log("  ✅ 飞书推送成功")
        else:
            log("  ⚠️  飞书推送失败")
        return success
    except Exception as e:
        log(f"  ⚠️  飞书推送异常: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="完整因子分析流水线")
    parser.add_argument("--phase", choices=["all", "recompute", "ic", "select", "backtest", "evaluate", "push"],
                       default="all", help="指定运行阶段")
    parser.add_argument("--top-n", type=int, default=10, help="Top N 因子数量")
    parser.add_argument("--feishu-url", default=None, help="飞书 Webhook URL")
    parser.add_argument("--dry-run", action="store_true", help="只检查不执行")
    args = parser.parse_args()
    
    t_start = time.time()
    log("\n" + "=" * 70)
    log("  完整因子分析流水线启动")
    log(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)
    
    results = {
        'ic_df': pd.DataFrame(),
        'stocks_df': pd.DataFrame(),
        'backtest_metrics': {},
        'performance_metrics': {}
    }
    
    # Phase 1: 因子重算
    if args.phase in ["all", "recompute"]:
        if not phase_recompute_factors(args.dry_run):
            log("❌ 因子重算失败")
            return 1
    
    # Phase 2: IC 分析
    if args.phase in ["all", "ic"]:
        results['ic_df'] = phase_ic_analysis(feishu_url=args.feishu_url)
        if results['ic_df'].empty:
            log("⚠️  IC 分析结果为空")
    
    # Phase 3: 选股
    if args.phase in ["all", "select"]:
        if results['ic_df'].empty:
            log("⚠️  没有 IC 结果，跳过选股")
        else:
            results['stocks_df'] = phase_stock_selection(results['ic_df'], top_n=args.top_n)
    
    # Phase 4: 回测
    if args.phase in ["all", "backtest"]:
        results['backtest_metrics'] = phase_backtest()
    
    # Phase 5: 绩效评估
    if args.phase in ["all", "evaluate"]:
        results['performance_metrics'] = phase_performance_evaluation(results['backtest_metrics'])
    
    # Phase 6: 飞书推送
    if args.phase in ["all", "push"]:
        if results['ic_df'].empty:
            log("⚠️  没有 IC 结果，跳过推送")
        else:
            phase_feishu_push(results['ic_df'], results['stocks_df'], 
                            results['performance_metrics'], feishu_url=args.feishu_url)
    
    # 保存汇总结果
    summary = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'duration_s': time.time() - t_start,
        'ic_factors': len(results['ic_df']),
        'backtest_return': results['backtest_metrics'].get('total_return', 0),
        'sharpe_ratio': results['performance_metrics'].get('sharpe', 0),
        'max_drawdown': results['performance_metrics'].get('max_drawdown', 0)
    }
    
    summary_file = cfg.PROJECT_ROOT / "pipeline_summary.json"
    import json
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    log(f"\n{'=' * 70}")
    log(f"  流水线完成! 总耗时: {time.time() - t_start:.1f}s")
    log(f"  汇总结果已保存: {summary_file}")
    log(f"{'=' * 70}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
