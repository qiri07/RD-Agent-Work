#!/usr/bin/env python3
"""
内存优化工具模块
================
提供内存管理、环境变量设置等通用工具函数。
从 factor_scan_mem_optimized.py 中提取。
"""

import os
import resource


def rss_mb():
    """获取当前进程的 RSS（MB）"""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def check_memory(tag="", soft_limit=2000, hard_limit=4000):
    """内存检查，超限时返回 False"""
    mem = rss_mb()
    if mem > hard_limit:
        print(f"[FATAL] {tag}: 内存超限 {mem:.0f}MB > {hard_limit}MB，跳过")
        return False
    if mem > soft_limit:
        print(f"[WARN]  {tag}: 内存 {mem:.0f}MB > {soft_limit}MB")
    return True


def setup_memory_env():
    """设置内存优化相关的环境变量"""
    os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "-1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")


# 启动时自动设置
setup_memory_env()
