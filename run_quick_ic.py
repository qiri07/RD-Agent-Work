#!/usr/bin/env python3
"""
快速IC分析 - 处理已重算的66个因子
使用numpy加速，避免pandas性能瓶颈
"""
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from pathlib import Path
import time
import sys

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg

def compute_ic_fast(factor_series, returns_series):
    """快速计算Spearman IC"""
    # 使用rank计算Spearman相关
    f_rank = factor_series.rank(pct=True)
    r_rank = returns_series.rank(pct=True)
    # Pearson相关 = Spearman相关
    corr = np.corrcoef(f_rank.values, r_rank.values)[0, 1]
    return corr

def main():
    print("=" * 70)
    print("  快速IC分析 - 重算因子版本")
    print("=" * 70)
    t_main = time.time()
    
    WS = cfg.RDAGENT_WORKSPACE
    SRC_PQ = cfg.DAILY_PV_FULL_PQ
    
    # Step 1: 加载价格数据，计算前向收益率
    print("\n1. 加载价格数据并计算收益率...")
    t0 = time.time()
    df = pd.read_parquet(SRC_PQ)
    df_reset = df.reset_index()
    df_reset["ret_5d"] = df_reset.groupby("instrument")["$close"].pct_change(5).shift(-5)
    ret_df = df_reset[["date", "instrument", "ret_5d"]].dropna()
    
    # 构建numpy查找数组
    date_codes = pd.Categorical(ret_df["date"].values).codes
    inst_codes = pd.Categorical(ret_df["instrument"].values).codes
    max_inst = inst_codes.max() + 1
    ret_keys = date_codes.astype(np.int64) * (max_inst + 1) + inst_codes.astype(np.int64)
    ret_vals = ret_df["ret_5d"].values.astype(np.float64)
    ret_lookup = dict(zip(ret_keys, ret_vals))
    
    print(f"   收益率数据: {len(ret_lookup):,} 条 ({time.time()-t0:.1f}s)")
    
    # Step 2: 找出已重算的66个session
    print("\n2. 扫描已重算的因子...")
    sessions_dir = sorted([d for d in WS.iterdir() if d.is_dir() and (d / "result.h5").exists()])
    print(f"   找到 {len(sessions_dir)} 个有result.h5的session")
    
    # Step 3: 逐因子计算IC
    print("\n3. 开始IC分析...")
    all_results = []
    
    for idx, d in enumerate(sessions_dir, 1):
        try:
            h5 = d / "result.h5"
            df_h5 = pd.read_hdf(h5, key="data")
            col = df_h5.columns[0]
            
            # 提取因子值
            s = df_h5[col].dropna().reset_index()
            s.columns = ["datetime", "instrument", "factor_val"]
            
            if len(s) < 100:
                continue
            
            # 转换为numpy
            f_vals = s["factor_val"].values.astype(np.float64)
            dates_m = s["datetime"].values
            insts_m = s["instrument"].values
            
            # 构建lookup keys
            d_codes = pd.Categorical(dates_m).codes
            i_codes = pd.Categorical(insts_m).codes
            max_i = i_codes.max() + 1
            keys = (d_codes.astype(np.int64) * (max_i + 1) + i_codes.astype(np.int64)).tolist()
            
            # 查找收益率
            rets = np.array([ret_lookup.get(k, np.nan) for k in keys], dtype=np.float64)
            mask = ~np.isnan(rets)
            f_clean = f_vals[mask]
            r_clean = rets[mask]
            
            if len(f_clean) < 100:
                continue
            
            # 计算IC
            ic_global = float(np.corrcoef(f_clean, r_clean)[0, 1])
            
            # 年度IC
            year_arr = pd.to_datetime(dates_m[mask]).year
            yearly_ic = {}
            for y in [2023, 2024, 2025, 2026]:
                y_mask = year_arr == y
                if y_mask.sum() < 20:
                    continue
                yearly_ic[y] = float(np.corrcoef(f_clean[y_mask], r_clean[y_mask])[0, 1])
            
            # Top/Bottom Decile收益
            decile = (f_clean - f_clean.min()) / (f_clean.max() - f_clean.min() + 1e-10)
            top_mask = decile >= 0.9
            bot_mask = decile <= 0.1
            top_rets = r_clean[top_mask]
            bot_rets = r_clean[bot_mask]
            
            all_results.append({
                "factor_id": d.name,
                "factor_name": col,
                "IC_5d": ic_global,
                "IC_t_5d": ic_global * np.sqrt(len(f_clean)) / max(1, np.std(f_clean)),
                "IC_pos_5d": (f_clean > 0).sum() / len(f_clean),
                "n_obs": len(f_clean),
                "top10_mean_ret": float(np.mean(top_rets)) * 100 if len(top_rets) > 0 else np.nan,
                "bot10_mean_ret": float(np.mean(bot_rets)) * 100 if len(bot_rets) > 0 else np.nan,
                "top10_med_ret": float(np.median(top_rets)) * 100 if len(top_rets) > 0 else np.nan,
                "bot10_med_ret": float(np.median(bot_rets)) * 100 if len(bot_rets) > 0 else np.nan,
                "yearly_ic": yearly_ic,
            })
            
            if idx % 10 == 0:
                print(f"   已处理 {idx}/{len(sessions_dir)} 个因子...")
                
        except Exception as e:
            print(f"   ⚠ {d.name[:12]}: {e}")
    
    del ret_lookup
    import gc
    gc.collect()
    
    print(f"\n   共处理 {len(all_results)} 个因子 ({time.time()-t_main:.1f}s)")
    
    # Step 4: 构建结果DataFrame
    rows = []
    for r in all_results:
        rows.append({
            "factor_id": r["factor_id"],
            "factor_name": r["factor_name"],
            "IC_5d": r["IC_5d"],
            "IC_t_5d": r["IC_t_5d"],
            "IC_pos_5d": r["IC_pos_5d"],
            "n_obs": r["n_obs"],
            "top10_mean_ret": r["top10_mean_ret"],
            "bot10_mean_ret": r["bot10_mean_ret"],
            "top10_med_ret": r["top10_med_ret"],
            "bot10_med_ret": r["bot10_med_ret"],
        })
    
    df_result = pd.DataFrame(rows)
    df_result = df_result.sort_values("IC_5d", key=abs, ascending=False)
    df_result["abs_IC"] = df_result["IC_5d"].abs()
    
    # Step 5: 输出结果
    print(f"\n{'='*70}")
    print(f"  📊 因子 IC 分析总览 (Top 20)")
    print(f"{'='*70}")
    cols_disp = ["factor_id", "factor_name", "IC_5d", "IC_t_5d", "IC_pos_5d", "n_obs", "top10_med_ret", "bot10_med_ret"]
    print(df_result[cols_disp].head(20).to_string(index=False))
    
    # 统计摘要
    print(f"\n{'='*70}")
    print(f"  📈 IC 统计摘要")
    print(f"{'='*70}")
    print(f"  总因子数:        {len(df_result)}")
    print(f"  IC 均值:         {df_result['IC_5d'].mean():+.4f}")
    print(f"  IC 中位数:       {df_result['IC_5d'].median():+.4f}")
    print(f"  IC 标准差:       {df_result['IC_5d'].std():.4f}")
    print(f"  IC 阳性率:       {df_result['IC_pos_5d'].mean():.3f}")
    print(f"  |IC| > 0.03:    {(df_result['abs_IC'] > 0.03).sum()} 个")
    print(f"  |IC| > 0.02:    {(df_result['abs_IC'] > 0.02).sum()} 个")
    print(f"  |IC| > 0.01:    {(df_result['abs_IC'] > 0.01).sum()} 个")
    print(f"  Top10 中位收益:  {df_result['top10_med_ret'].mean():+.3f}%")
    print(f"  Bot10 中位收益:  {df_result['bot10_med_ret'].mean():+.3f}%")
    spread = df_result['top10_med_ret'].mean() - df_result['bot10_med_ret'].mean()
    print(f"  Top-Bot Spread:  {spread:+.3f}%")
    
    # Top 20 详情
    print(f"\n{'='*70}")
    print(f"  🏆 Top 20 最强因子 (按 |IC| 排序)")
    print(f"{'='*70}")
    for rank, (_, row) in enumerate(df_result.head(20).iterrows(), 1):
        fname = str(row['factor_name'])[:30] if pd.notna(row['factor_name']) else row['factor_id'][:12]
        print(f"  #{rank:2d}  {row['factor_id']:<40s}  IC={row['IC_5d']:>+8.4f}  pos={row['IC_pos_5d']:>+6.3f}  top10={row['top10_med_ret']:>+7.2f}%  bot10={row['bot10_med_ret']:>+7.2f}%")
    
    # 保存结果
    out_csv = Path("ic_analysis_recomputed.csv")
    df_result.to_csv(out_csv, index=False)
    print(f"\n💾 IC结果已保存: {out_csv}")
    
    # 年度IC
    yearly_rows = []
    for r in all_results:
        for y, v in r.get("yearly_ic", {}).items():
            yearly_rows.append({
                "factor_id": r["factor_id"],
                "factor_name": r["factor_name"],
                "year": y,
                "IC": v,
            })
    
    if yearly_rows:
        df_y = pd.DataFrame(yearly_rows)
        df_y.to_csv("ic_analysis_yearly_recomputed.csv", index=False)
        print(f"💾 年度IC已保存: ic_analysis_yearly_recomputed.csv")
    
    print(f"\n总耗时: {time.time()-t_main:.1f}s")
    return df_result

if __name__ == "__main__":
    main()
