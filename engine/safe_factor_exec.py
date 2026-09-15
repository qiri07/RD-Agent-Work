#!/usr/bin/env python3
"""
因子脚本安全执行工具
=====================
用 importlib 替代 exec()，并校验代码安全性。
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional

# 禁止的危险模式（正则列表）
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r'\bos\.system\b', 'os.system 调用'),
    (r'\bos\.popen\b', 'os.popen 调用'),
    (r'\bsubprocess\.', 'subprocess 调用'),
    (r'\beval\s*\(', 'eval() 调用'),
    (r'\bexec\s*\(', 'exec() 调用'),
    (r'\b__import__\s*\(', '__import__() 调用'),
    (r'\bopen\s*\([^)]*,\s*["\']w', '文件写入操作'),
    (r'\bopen\s*\([^)]*,\s*["\']a', '文件追加操作'),
    (r'\bimport\s+os\b', '导入 os 模块'),
    (r'\bimport\s+subprocess\b', '导入 subprocess 模块'),
]


def validate_factor_code(code: str) -> list[str]:
    """校验因子代码安全性，返回违规项列表"""
    violations = []
    for pattern, desc in DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            violations.append(desc)
    return violations


def run_factor_script(factor_py: Path, extra_vars: Optional[dict] = None) -> tuple[bool, str]:
    """
    安全执行因子脚本（使用 importlib，非 exec）
    
    Args:
        factor_py: factor.py 文件路径
        extra_vars: 额外注入的变量（如 df, pd, np）
    
    Returns:
        (success, info)
    """
    if not factor_py.exists():
        return False, "无 factor.py"

    code = factor_py.read_text(encoding="utf-8")

    # 安全校验
    violations = validate_factor_code(code)
    if violations:
        return False, f"安全校验失败: {', '.join(violations)}"

    # 用 importlib 加载模块
    spec = importlib.util.spec_from_file_location("factor_module", factor_py)
    if spec is None or spec.loader is None:
        return False, "无法加载 factor.py 模块"

    module = importlib.util.module_from_spec(spec)
    namespace = {"__name__": "factor_module", "__file__": str(factor_py)}
    if extra_vars:
        namespace.update(extra_vars)

    try:
        spec.loader.exec_module(module)
        return True, "✅ 执行成功"
    except Exception as e:
        return False, f"❌ 执行失败: {str(e)[:120]}"


__all__ = ["validate_factor_code", "run_factor_script"]
