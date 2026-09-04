#!/usr/bin/env python3
"""
因子分析 + 选股 + 飞书推送 一体化脚本
=====================================
功能：
1. 运行 IC 因子分析 (run_ic_fast.py)
2. 基于 Top N 因子筛选股票
3. 推送结果到飞书

用法：
    python run_pipeline.py              # 完整流程
    python run_pipeline.py --ic-only    # 只跑 IC 分析
    python run_pipeline.py --stocks-only  # 只选股
    python run_pipeline.py --feishu-only --ic-results xxx.csv --stocks xxx.csv  # 仅推送
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg

from feishu_notify import send_combined_report


def run_ic_analysis():
    """运行 IC 因子分析"""
    print("\n" + "=" * 70)
    print("  📊 步骤 1/3: IC 因子分析")
    print("=" * 70)
    
    result = subprocess.run(
        [sys.executable, str(cfg.PROJECT_ROOT / "run_ic_fast.py")],
        cwd=str(BASE),
        capture_output=False,
    )
    return result.returncode == 0


def screen_stocks(ic_df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """
    基于 IC 结果筛选 Top N 因子对应的股票
    
    Args:
        ic_df: IC 分析结果 DataFrame
        top_n: 使用 Top N 个因子进行选股
    
    Returns:
        选股结果 DataFrame
    """
    print("\n" + "=" * 70)
    print("  🎯 步骤 2/3: 基于 Top 因子选股")
    print("=" * 70)
    
    # 获取 Top N 因子（按 |IC| 排序）
    ic_df_sorted = ic_df.copy()
    ic_df_sorted["_abs_ic"] = ic_df_sorted["IC_5d"].abs()
    top_factors = ic_df_sorted.nlargest(top_n, "_abs_ic")["factor_id"].tolist()
    
    print(f"  使用 Top {len(top_factors)} 个因子进行选股")
    for i, fid in enumerate(top_factors, 1):
        row = ic_df_sorted[ic_df_sorted["factor_id"] == fid].iloc[0]
        print(f"    {i}. {fid[:30]}  IC={row['IC_5d']:+.4f}")
    
    # 加载因子数据
    WS = cfg.PROJECT_ROOT / "git_ignore_folder" / "RD-Agent_workspace"
    SRC_PQ = cfg.PROJECT_ROOT / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv_full.parquet"
    
    print("\n  加载因子数据...")
    factor_dict = {}
    for fid in top_factors:
        h5 = WS / fid / "result.h5"
        if not h5.exists():
            print(f"    ⚠️  未找到: {h5}")
            continue
        try:
            df = pd.read_hdf(h5, key="data")
            col = df.columns[0]
            s = df[col].copy()
            if s.index.names[0] != "datetime":
                s.index = s.index.set_names(["datetime", "instrument"])
            s = s.reset_index()
            s.columns = ["datetime", "instrument", "factor_val"]
            factor_dict[fid] = s
            print(f"    ✅ {fid[:20]}  {len(s):,} rows")
        except Exception as e:
            print(f"    ❌ {fid[:20]}  {e}")
    
    if not factor_dict:
        print("  ❌ 没有可用因子数据！")
        return None
    
    # 获取最新交易日
    all_dates = []
    for s in factor_dict.values():
        all_dates.extend(s["datetime"].unique())
    latest_date = max(all_dates)
    print(f"\n  最新交易日: {latest_date}")
    
    # 在最新日期合成因子得分
    print("  合成综合得分...")
    day_data = {}
    for fid, s in factor_dict.items():
        day_rows = s[s["datetime"] == latest_date]
        day_data[fid] = day_rows.set_index("instrument")["factor_val"]
    
    combined = pd.DataFrame(day_data)
    combined = combined.dropna()
    
    # Z-score 标准化
    combined_std = combined.copy()
    for col in combined.columns:
        mean = combined[col].mean()
        std = combined[col].std()
        if std > 0:
            combined_std[col] = (combined[col] - mean) / std
        else:
            combined_std[col] = 0
    
    # 等权合成
    weights = 1.0 / len(combined_std.columns)
    combined_std["composite_score"] = (combined_std * weights).sum(axis=1)
    
    # 排序取 Top K
    top_k = 10
    ranked = combined_std.copy()
    ranked["rank"] = ranked["composite_score"].rank(ascending=False, method="dense")
    top_stocks = ranked.nlargest(top_k, "composite_score")
    
    # 保存结果
    out_df = top_stocks.reset_index()[["instrument", "composite_score", "rank"] + 
                                       [c for c in top_stocks.columns if c not in ["composite_score", "rank"]]]
    # 确保列顺序正确
    out_df = out_df[["rank", "instrument", "composite_score"] + 
                    [c for c in out_df.columns if c not in ["rank", "instrument", "composite_score"]]]
    
    out_csv = cfg.PROJECT_ROOT / "top10_stocks_new.csv"
    out_df.to_csv(out_csv, index=False)
    print(f"\n  💾 已保存: {out_csv}")
    
    print(f"\n{'='*70}")
    print(f"  🏆 Top {top_k} 股票 (最新日: {latest_date})")
    print(f"{'='*70}")
    for _, row in out_df.iterrows():
        print(f"  #{int(row['rank']):2d}  {row['instrument']:12s}  得分={row['composite_score']:.4f}")
    
    return out_df


def push_feishu(ic_df: pd.DataFrame, stocks_df: pd.DataFrame):
    """推送结果到飞书"""
    print("\n" + "=" * 70)
    print("  📱 步骤 3/3: 推送飞书通知")
    print("=" * 70)
    
    try:
        success = send_combined_report(ic_df, stocks_df, top_n=10)
        if success:
            print("  ✅ 飞书推送成功")
        else:
            print("  ⚠️  飞书推送失败")
    except Exception as e:
        print(f"  ⚠️  飞书推送异常: {e}")


def main():
    parser = argparse.ArgumentParser(description="因子分析 + 选股 + 飞书推送一体化")
    parser.add_argument("--ic-only", action="store_true", help="只运行 IC 分析")
    parser.add_argument("--stocks-only", action="store_true", help="只选股（不重新计算 IC）")
    parser.add_argument("--feishu-only", action="store_true", help="只推送飞书（使用已有结果文件）")
    parser.add_argument("--ic-results", help="指定 IC 结果 CSV 路径")
    parser.add_argument("--stocks", help="指定选股结果 CSV 路径")
    parser.add_argument("--top-n", type=int, default=10, help="Top N 因子数量 (默认 10)")
    args = parser.parse_args()
    
    t_start = time.time()
    
    if args.feishu_only:
        # 仅推送模式
        ic_path = Path(args.ic_results) if args.ic_results else cfg.PROJECT_ROOT / "ic_scan_results_new.csv"
        stocks_path = Path(args.stocks) if args.stocks else cfg.PROJECT_ROOT / "top10_stocks_new.csv"
        
        if not ic_path.exists():
            print(f"❌ IC 结果文件不存在: {ic_path}")
            return 1
        if not stocks_path.exists():
            print(f"❌ 选股结果文件不存在: {stocks_path}")
            return 1
        
        ic_df = pd.read_csv(ic_path)
        stocks_df = pd.read_csv(stocks_path)
        push_feishu(ic_df, stocks_df)
        
    elif args.ic_only:
        # 只运行 IC 分析（内部已包含飞书推送）
        if not run_ic_analysis():
            print("❌ IC 分析失败")
            return 1
            
    elif args.stocks_only:
        # 只选股
        ic_path = cfg.PROJECT_ROOT / "ic_scan_results_new.csv"
        if not ic_path.exists():
            print(f"❌ IC 结果文件不存在，请先运行 IC 分析: {ic_path}")
            return 1
        
        ic_df = pd.read_csv(ic_path)
        stocks_df = screen_stocks(ic_df, top_n=args.top_n)
        
        if stocks_df is not None:
            push_feishu(ic_df, stocks_df)
            
    else:
        # 完整流程
        if not run_ic_analysis():
            print("❌ IC 分析失败，终止流程")
            return 1
        
        ic_df = pd.read_csv(cfg.PROJECT_ROOT / "ic_scan_results_new.csv")
        stocks_df = screen_stocks(ic_df, top_n=args.top_n)
        
        if stocks_df is not None:
            push_feishu(ic_df, stocks_df)
    
    print(f"\n✅ 完成！总耗时: {time.time()-t_start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
