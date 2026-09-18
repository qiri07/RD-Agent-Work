#!/usr/bin/env python3
from __future__ import annotations
"""
指数成分股获取脚本
==================
定期获取沪深300、中证500、中证100、上证50的成分股，
并保存到历史快照目录。

用法:
    python fetch_index_constituents.py          # 获取当前快照
    python fetch_index_constituents.py --date 2024-01-01  # 获取指定日期（仅支持当前）
    python fetch_index_constituents.py --history  # 尝试生成历史快照
"""

import argparse
import baostock as bs
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import json

# 配置
OUT_DIR = Path("/run/media/onai/MyDisk/Work/shared_data/qlib_data/instruments")
HISTORY_DIR = OUT_DIR / "history"
LOG_FILE = Path("/run/media/onai/MyDisk/Work/shared_data/qlib_data/instruments/fetch_log.jsonl")

# 指数映射
INDICES = {
    "csi300": {"query": "hs300", "count": 300},
    "csi500": {"query": "zz500", "count": 500},
    "csi100": {"query": "hs300", "count": 100, "note": "从 HS300 取前100只作为代理"},
    "sz50": {"query": "sz50", "count": 50},
}


def login_baostock():
    """登录 baostock"""
    lg = bs.login()
    if lg.error_code != '0':
        raise Exception(f"Baostock login failed: {lg.error_msg}")
    return lg


def logout_baostock():
    """登出 baostock"""
    bs.logout()


def query_index_stocks(index_name, limit=None):
    """查询指数成分股"""
    if index_name == "hs300":
        rs = bs.query_hs300_stocks()
    elif index_name == "zz500":
        rs = bs.query_zz500_stocks()
    elif index_name == "sz50":
        rs = bs.query_sz50_stocks()
    else:
        raise ValueError(f"Unknown index: {index_name}")
    
    if rs.error_code != '0':
        raise Exception(f"Query {index_name} failed: {rs.error_msg}")
    
    data_list = []
    while (rs.error_code == '0') and rs.next():
        if limit and len(data_list) >= limit:
            break
        data_list.append(rs.get_row_data())
    
    return data_list


def format_qlib_code(code):
    """转换代码格式: sh.600000 -> SH600000"""
    return code.replace('.', '').upper()


def save_index_file(index_name, stocks, date_str):
    """保存指数文件为 qlib 格式"""
    lines = []
    for row in stocks:
        date, code, name = row[0], row[1], row[2]
        qlib_code = format_qlib_code(code)
        # qlib 格式: code\tstart_date\tend_date
        lines.append(f"{qlib_code}\t{date_str}\t{date_str}")
    
    # 保存到当前文件
    out_path = OUT_DIR / f"{index_name}.txt"
    out_path.write_text('\n'.join(lines) + '\n')
    
    # 保存到历史快照
    snapshot_path = HISTORY_DIR / f"{index_name}_{date_str.replace('-', '')}.txt"
    snapshot_path.write_text('\n'.join(lines) + '\n')
    
    return len(lines), out_path, snapshot_path


def log_fetch(index_name, count, duration_ms, success=True, error=None):
    """记录获取日志"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "index": index_name,
        "count": count,
        "duration_ms": duration_ms,
        "success": success,
        "error": error
    }
    
    with open(LOG_FILE, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')
    
    return log_entry


def generate_history_snippets(years=3):
    """
    生成历史快照片段
    注意：baostock 不提供历史成分股接口，这里基于现有数据和合理假设生成
    
    策略：
    1. 从旧数据 (cn_data_old_20260911) 提取历史成分股
    2. 结合当前成分股，生成时间序列快照
    """
    from pathlib import Path
    
    OLD_DATA = Path.home() / ".qlib/qlib_data/cn_data_old_20260911/instruments"
    
    if not OLD_DATA.exists():
        print("  ⚠️  旧数据不存在，跳过历史生成")
        return
    
    print(f"\n生成历史快照 (过去 {years} 年)...")
    
    # 定义历史时间节点
    dates = []
    today = datetime.now()
    for y in range(today.year - years, today.year + 1):
        for m in [1, 4, 7, 10]:  # 每季度末
            dates.append(f"{y}-{m:02d}-01")
    
    dates.sort()
    
    for index_name in ["csi300", "csi500", "sz50"]:
        old_file = OLD_DATA / f"{index_name}.txt"
        if not old_file.exists():
            continue
        
        print(f"\n  {index_name}:")
        
        # 读取旧数据
        old_stocks = {}
        with open(old_file) as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 3:
                    code, start, end = parts[0], parts[1], parts[2]
                    old_stocks[code] = (start, end)
        
        # 读取当前数据
        current_file = OUT_DIR / f"{index_name}.txt"
        current_stocks = {}
        if current_file.exists():
            with open(current_file) as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) >= 3:
                        code, start, end = parts[0], parts[1], parts[2]
                        current_stocks[code] = (start, end)
        
        # 为每个历史节点生成快照
        for date_str in dates:
            # 简化处理：使用接近日期的旧数据或当前数据
            snapshot_stocks = []
            
            for code, (start, end) in old_stocks.items():
                if start <= date_str <= end:
                    snapshot_stocks.append(f"{code}\t{start}\t{end}")
            
            if not snapshot_stocks and current_stocks:
                # 如果没有旧数据匹配，使用当前数据
                for code, (start, end) in current_stocks.items():
                    snapshot_stocks.append(f"{code}\t{date_str}\t{date_str}")
            
            if snapshot_stocks:
                snapshot_path = HISTORY_DIR / f"{index_name}_{date_str.replace('-', '')}.txt"
                snapshot_path.write_text('\n'.join(snapshot_stocks) + '\n')
        
        print(f"    已生成 {len(dates)} 个历史快照")


def main():
    parser = argparse.ArgumentParser(description="获取指数成分股")
    parser.add_argument("--date", help="指定日期（仅支持当前）")
    parser.add_argument("--history", action="store_true", help="生成历史快照")
    parser.add_argument("--years", type=int, default=3, help="历史年份数 (默认: 3)")
    args = parser.parse_args()
    
    print("=" * 60)
    print("  指数成分股获取工具")
    print("=" * 60)
    
    # 确保目录存在
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # 登录
    print("\n登录 Baostock...")
    login_baostock()
    
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"当前日期: {today}\n")
        
        results = []
        
        for index_name, config in INDICES.items():
            print(f"查询 {index_name}...")
            start_time = datetime.now()
            
            try:
                # 对于 csi100，从 hs300 取前100只
                query_name = config["query"]
                limit = config.get("count")
                
                stocks = query_index_stocks(query_name, limit=limit)
                count, out_path, snapshot_path = save_index_file(index_name, stocks, today)
                
                duration = (datetime.now() - start_time).total_seconds() * 1000
                log_fetch(index_name, count, duration)
                
                note = ""
                if index_name == "csi100":
                    note = " (来自HS300前100只)"
                print(f"  ✅ {count} 只 -> {out_path}{note}")
                print(f"     快照 -> {snapshot_path}")
                
                results.append({"index": index_name, "count": count, "success": True})
                
            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds() * 1000
                log_fetch(index_name, 0, duration, success=False, error=str(e))
                print(f"  ❌ 错误: {e}")
                results.append({"index": index_name, "count": 0, "success": False, "error": str(e)})
        
        # 生成历史快照
        if args.history:
            generate_history_snippets(args.years)
        
        print("\n" + "=" * 60)
        print("  完成!")
        print(f"  成功: {sum(1 for r in results if r.get('success'))}/{len(results)}")
        print("=" * 60)
        
    finally:
        logout_baostock()


if __name__ == "__main__":
    main()
