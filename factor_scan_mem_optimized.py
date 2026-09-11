#!/usr/bin/env python3
"""
因子 IC 扫描 入口脚本
======================
用法:
    python3 factor_scan_mem_optimized.py --scan        # 运行完整 IC 扫描
    python3 factor_scan_mem_optimized.py --cleanup     # 清理冗余文件
    python3 factor_scan_mem_optimized.py --archive-traces [DIR]
    python3 factor_scan_mem_optimized.py --scan-sizes [ROOT]
    python3 factor_scan_mem_optimized.py --mem-limit N
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ic_scan_utils import (
    scan_all_factors, cleanup_disk_space,
    archive_traces, scan_sizes,
    SOFT_MEM_LIMIT_MB, HARD_MEM_LIMIT_MB,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RD-Agent 内存高效因子扫描")
    parser.add_argument("--scan", action="store_true", help="运行完整 IC 扫描")
    parser.add_argument("--cleanup", action="store_true", help="清理冗余文件释放磁盘空间")
    parser.add_argument("--archive-traces", nargs="?",
                        const="./git_ignore_folder/RD-Agent_workspace/trace",
                        metavar="TRACE_DIR", help="归档过期的 trace JSON 文件")
    parser.add_argument("--scan-sizes", nargs="?",
                        const="./git_ignore_folder/RD-Agent_workspace",
                        metavar="ROOT", help="扫描目录中 >=1MB 的大文件（诊断用）")
    parser.add_argument("--mem-limit", type=int, default=HARD_MEM_LIMIT_MB,
                        help=f"硬内存限制 (MB, 默认 {HARD_MEM_LIMIT_MB})")
    args = parser.parse_args()

    if args.scan:
        scan_all_factors(soft_limit=SOFT_MEM_LIMIT_MB, hard_limit=args.mem_limit)
    elif args.cleanup:
        cleanup_disk_space()
    elif args.archive_traces is not None:
        archive_traces(args.archive_traces)
    elif args.scan_sizes is not None:
        scan_sizes(args.scan_sizes)
    else:
        parser.print_help()
