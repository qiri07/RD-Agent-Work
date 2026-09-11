#!/usr/bin/env python3
"""
缓存模块测试
============
测试 engine/cache.py 的所有功能。
"""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from engine.cache import (
    CacheManager, get_cache, clear_global_cache,
    load_cached_parquet, load_cached_hdf, cache_with_ttl
)


class TestCacheWithTTL(unittest.TestCase):
    """测试 cache_with_ttl 装饰器"""

    def test_basic_caching(self):
        """基本缓存功能"""
        call_count = [0]

        @cache_with_ttl(maxsize=2)
        def expensive_func(x):
            call_count[0] += 1
            return x * 2

        # 第一次调用
        result1 = expensive_func(5)
        self.assertEqual(result1, 10)
        self.assertEqual(call_count[0], 1)

        # 第二次调用相同参数应使用缓存
        result2 = expensive_func(5)
        self.assertEqual(result2, 10)
        self.assertEqual(call_count[0], 1)  # 仍只调用1次

        # 不同参数应重新计算
        result3 = expensive_func(3)
        self.assertEqual(result3, 6)
        self.assertEqual(call_count[0], 2)

    def test_cache_info(self):
        """缓存信息"""
        @cache_with_ttl(maxsize=2)
        def func(x):
            return x

        func(1)
        func(2)
        info = func.cache_info()
        self.assertEqual(info.hits, 0)
        self.assertEqual(info.misses, 2)

    def test_cache_clear(self):
        """清除缓存"""
        @cache_with_ttl(maxsize=2)
        def func(x):
            return x

        func(1)
        func(2)
        func.cache_clear()
        info = func.cache_info()
        self.assertEqual(info.currsize, 0)


class TestLoadCachedParquet(unittest.TestCase):
    """测试 load_cached_parquet"""

    def test_load_and_cache(self):
        """加载并缓存parquet文件"""
        with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as f:
            tmp_path = Path(f.name)
            df = pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})
            df.to_parquet(tmp_path)

        try:
            result = load_cached_parquet(tmp_path)
            self.assertIsInstance(result, pd.DataFrame)
            self.assertEqual(len(result), 3)
            self.assertEqual(list(result.columns), ['a', 'b'])
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_cache_reuse(self):
        """缓存复用"""
        with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as f:
            tmp_path = Path(f.name)
            df = pd.DataFrame({'a': [1, 2, 3]})
            df.to_parquet(tmp_path)

        try:
            # 两次加载应使用缓存
            result1 = load_cached_parquet(tmp_path)
            result2 = load_cached_parquet(tmp_path)
            self.assertEqual(len(result1), len(result2))
        finally:
            tmp_path.unlink(missing_ok=True)


class TestLoadCachedHDF(unittest.TestCase):
    """测试 load_cached_hdf"""

    def test_load_and_cache(self):
        """加载并缓存hdf文件"""
        with tempfile.NamedTemporaryFile(suffix='.h5', delete=False) as f:
            tmp_path = Path(f.name)
            df = pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})
            df.to_hdf(tmp_path, key='data', mode='w')

        try:
            result = load_cached_hdf(tmp_path, key='data')
            self.assertIsInstance(result, pd.DataFrame)
            self.assertEqual(len(result), 3)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_cache_reuse(self):
        """缓存复用"""
        with tempfile.NamedTemporaryFile(suffix='.h5', delete=False) as f:
            tmp_path = Path(f.name)
            df = pd.DataFrame({'a': [1, 2, 3]})
            df.to_hdf(tmp_path, key='data', mode='w')

        try:
            result1 = load_cached_hdf(tmp_path, key='data')
            result2 = load_cached_hdf(tmp_path, key='data')
            self.assertEqual(len(result1), len(result2))
        finally:
            tmp_path.unlink(missing_ok=True)


class TestCacheManagerAdvanced(unittest.TestCase):
    """测试 CacheManager 高级功能"""

    def test_set_get(self):
        """设置和获取"""
        cache = CacheManager()
        cache.set('key1', 'value1')
        self.assertEqual(cache.get('key1'), 'value1')

    def test_get_missing(self):
        """获取不存在的key返回None"""
        cache = CacheManager()
        self.assertIsNone(cache.get('missing'))

    def test_clear(self):
        """清除缓存"""
        cache = CacheManager()
        cache.set('key1', 'value1')
        cache.set('key2', 'value2')
        cache.clear()
        self.assertIsNone(cache.get('key1'))
        self.assertIsNone(cache.get('key2'))

    def test_get_size_mb_empty(self):
        """空缓存大小为0"""
        cache = CacheManager()
        size = cache.get_size_mb()
        self.assertLessEqual(size, 0.01)  # 接近0

    def test_get_size_mb_with_data(self):
        """有数据时缓存大小正确"""
        cache = CacheManager()
        cache.set('large_key', 'x' * 10000)  # 10KB
        size = cache.get_size_mb()
        self.assertGreater(size, 0.009)  # 至少9KB

    def test_different_keys(self):
        """不同key存储不同值"""
        cache = CacheManager()
        cache.set('a', 1)
        cache.set('b', 2)
        cache.set('c', 3)
        self.assertEqual(cache.get('a'), 1)
        self.assertEqual(cache.get('b'), 2)
        self.assertEqual(cache.get('c'), 3)


class TestGlobalCache(unittest.TestCase):
    """测试全局缓存"""

    def setUp(self):
        clear_global_cache()

    def test_get_cache(self):
        """获取全局缓存实例"""
        cache = get_cache()
        self.assertIsInstance(cache, CacheManager)

    def test_clear_global_cache(self):
        """清除全局缓存"""
        cache = get_cache()
        cache.set('key', 'value')
        clear_global_cache()
        self.assertIsNone(get_cache().get('key'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
