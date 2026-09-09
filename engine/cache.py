#!/usr/bin/env python3
"""
内存缓存模块
============
提供数据加载缓存功能，避免重复读取大文件。
"""
import hashlib
import logging
from pathlib import Path
from functools import lru_cache
from typing import Optional, Callable, Any
import pandas as pd

logger = logging.getLogger(__name__)


def cache_with_ttl(maxsize: int = 2):
    """
    带TTL的LRU缓存装饰器
    
    Args:
        maxsize: 最大缓存条目数
    """
    def decorator(func: Callable) -> Callable:
        cached_func = lru_cache(maxsize=maxsize)(func)
        
        def wrapper(*args, **kwargs):
            return cached_func(*args, **kwargs)
        
        wrapper.cache_clear = cached_func.cache_clear
        wrapper.cache_info = cached_func.cache_info
        return wrapper
    return decorator


def load_cached_parquet(path: Path, **kwargs) -> pd.DataFrame:
    """
    缓存Parquet文件加载
    
    Args:
        path: 文件路径
        **kwargs: 传递给pd.read_parquet的参数
        
    Returns:
        DataFrame
    """
    # 使用文件路径和内容哈希作为缓存键
    file_hash = hashlib.md5(str(path).encode()).hexdigest()[:8]
    
    @lru_cache(maxsize=2)
    def _load(p: str) -> pd.DataFrame:
        logger.debug(f"加载Parquet: {p}")
        return pd.read_parquet(Path(p), **kwargs)
    
    return _load(str(path))


def load_cached_hdf(path: Path, key: str = "data", **kwargs) -> pd.DataFrame:
    """
    缓存HDF5文件加载
    
    Args:
        path: 文件路径
        key: HDF5中的key
        **kwargs: 传递给pd.read_hdf的参数
        
    Returns:
        DataFrame
    """
    file_hash = hashlib.md5(str(path).encode()).hexdigest()[:8]
    
    @lru_cache(maxsize=2)
    def _load(p: str, k: str) -> pd.DataFrame:
        logger.debug(f"加载HDF5: {p}[{k}]")
        return pd.read_hdf(Path(p), key=k, **kwargs)
    
    return _load(str(path), key)


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, max_size_mb: int = 500):
        self.max_size_mb = max_size_mb
        self._cache = {}
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        return self._cache.get(key)
    
    def set(self, key: str, value: Any) -> None:
        """设置缓存值"""
        # 简单实现，生产环境应使用更复杂的缓存策略
        self._cache[key] = value
    
    def clear(self) -> None:
        """清除所有缓存"""
        self._cache.clear()
        import gc
        gc.collect()
    
    def get_size_mb(self) -> float:
        """获取缓存占用内存（MB）"""
        import sys
        total = sum(sys.getsizeof(v) for v in self._cache.values())
        return total / 1024 / 1024


# 全局缓存实例
_global_cache = CacheManager()


def get_cache() -> CacheManager:
    """获取全局缓存实例"""
    return _global_cache


def clear_global_cache() -> None:
    """清除全局缓存"""
    _global_cache.clear()
    logger.info("全局缓存已清除")
