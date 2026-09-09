#!/usr/bin/env python3
"""
日志配置模块
============
统一配置项目日志系统。
"""
import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    console_output: bool = True,
) -> None:
    """
    配置项目日志系统
    
    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径，None则不输出到文件
        console_output: 是否输出到控制台
    """
    # 创建格式化器
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 清除已有处理器
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # 控制台处理器
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # 文件处理器
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # 抑制第三方库的冗余日志
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("pandas").setLevel(logging.WARNING)
    
    logging.info(f"日志系统已初始化，级别={level}")


def get_logger(name: str) -> logging.Logger:
    """
    获取命名logger
    
    Args:
        name: logger名称，通常为 __name__
        
    Returns:
        Logger实例
    """
    return logging.getLogger(name)


# 默认logger实例
logger = get_logger("rdagent")
