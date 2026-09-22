#!/usr/bin/env python3
from __future__ import annotations

"""
config.py 单元测试 — 不使用 pytest，用 unittest 兼容
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# Add project root to path so config can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def reload_config():
    """清除缓存并重新导入 config"""
    for mod in list(sys.modules.keys()):
        if mod in ("config", "feishu_notify"):
            del sys.modules[mod]


class TestConfigPaths(unittest.TestCase):
    def setUp(self):
        reload_config()

    def test_project_root(self):
        import config as cfg
        self.assertIsInstance(cfg.PROJECT_ROOT, Path)
        self.assertTrue(cfg.PROJECT_ROOT.exists())

    def test_data_paths_exist(self):
        import config as cfg
        self.assertIsInstance(cfg.GIT_IGNORE, Path)
        self.assertIsInstance(cfg.FACTOR_SOURCE, Path)
        self.assertIsInstance(cfg.RDAGENT_WORKSPACE, Path)

    def test_string_paths(self):
        import config as cfg
        self.assertEqual(cfg.RDAGENT_WORKSPACE_STR, str(cfg.RDAGENT_WORKSPACE))
        self.assertEqual(cfg.FACTOR_SOURCE_STR, str(cfg.FACTOR_SOURCE))


class TestConfigEnvOverride(unittest.TestCase):
    def test_ic_params_override(self):
        reload_config()
        with mock.patch.dict(os.environ, {
            "IC_MIN_DAILY_STOCKS": "100",
            "IC_TOP_N_DEFAULT": "20",
        }):
            import config as cfg
            self.assertEqual(cfg.IC_MIN_DAILY_STOCKS, 100)
            self.assertEqual(cfg.IC_TOP_N_DEFAULT, 20)

    def test_backtest_params_override(self):
        reload_config()
        with mock.patch.dict(os.environ, {
            "BACKTEST_TOP_K": "20",
            "BACKTEST_HOLD_DAYS": "10",
        }):
            import config as cfg
            self.assertEqual(cfg.BACKTEST_TOP_K, 20)
            self.assertEqual(cfg.BACKTEST_HOLD_DAYS, 10)


class TestFeishuConfig(unittest.TestCase):
    def test_not_configured_by_default(self):
        env = {k: v for k, v in os.environ.items() if k != "FEISHU_WEBHOOK_URL"}
        reload_config()
        with mock.patch.dict(os.environ, env, clear=True):
            # 如果 token_step.txt 存在且含 webhook，则 configured=True；否则=False
            import config as cfg
            # 只验证占位符检测逻辑
            self.assertFalse("YOUR_WEBHOOK" in cfg.FEISHU_WEBHOOK_URL)

    def test_configured_via_env(self):
        reload_config()
        with mock.patch.dict(os.environ, {
            "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test123"
        }):
            import config as cfg
            self.assertTrue(cfg.is_feishu_configured())
            self.assertEqual(cfg.FEISHU_WEBHOOK_URL, "https://open.feishu.cn/open-apis/bot/v2/hook/test123")


class TestSplitDates(unittest.TestCase):
    def test_with_env(self):
        reload_config()
        with mock.patch.dict(os.environ, {
            "BACKTEST_SPLIT_DATE_PREV": "2026-09-01",
            "BACKTEST_SPLIT_DATE_CURR": "2026-09-02",
        }):
            import config as cfg
            prev, curr = cfg.get_split_dates()
            from datetime import datetime
            self.assertEqual(prev, datetime(2026, 9, 1))  # noqa: DTZ001
            self.assertEqual(curr, datetime(2026, 9, 2))  # noqa: DTZ001

    def test_without_env(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("BACKTEST_SPLIT_DATE_PREV", "BACKTEST_SPLIT_DATE_CURR")}
        reload_config()
        with mock.patch.dict(os.environ, env, clear=True):
            import config as cfg
            prev, curr = cfg.get_split_dates()
            self.assertIsNone(prev)
            self.assertIsNone(curr)


class TestWhitelistConfig(unittest.TestCase):
    def test_whitelist_from_env(self):
        reload_config()
        with mock.patch.dict(os.environ, {
            "WHITELIST_STOCKS": "SH600000,SH600001,SZ000001"
        }):
            import config as cfg
            self.assertEqual(cfg.WHITELIST_STOCKS, ["SH600000", "SH600001", "SZ000001"])
            self.assertTrue(cfg.is_whitelist_configured())

    def test_whitelist_from_env_file(self):
        """从 .env 文件读取白名单（当前 .env 已配置）"""
        reload_config()
        # 清除环境变量，确保从 .env 文件读取
        env = {k: v for k, v in os.environ.items() if k != "WHITELIST_STOCKS"}
        with mock.patch.dict(os.environ, env, clear=True):
            import config as cfg
            self.assertTrue(cfg.is_whitelist_configured())
            self.assertGreater(len(cfg.WHITELIST_STOCKS), 0)

    def test_whitelist_env_overrides_file(self):
        """环境变量 WHITELIST_STOCKS 优先于 .env 文件"""
        reload_config()
        env = {k: v for k, v in os.environ.items() if k != "WHITELIST_STOCKS"}
        with mock.patch.dict(os.environ, {**env, "WHITELIST_STOCKS": "SH600000,SZ000001"}):
            import config as cfg
            self.assertEqual(cfg.WHITELIST_STOCKS, ["SH600000", "SZ000001"])

    def test_whitelist_whitespace_handling(self):
        reload_config()
        with mock.patch.dict(os.environ, {
            "WHITELIST_STOCKS": " SH600000 , SH600001 , SZ000001 "
        }):
            import config as cfg
            self.assertEqual(cfg.WHITELIST_STOCKS, ["SH600000", "SH600001", "SZ000001"])

    def test_whitelist_single_stock(self):
        reload_config()
        with mock.patch.dict(os.environ, {
            "WHITELIST_STOCKS": "SH600000"
        }):
            import config as cfg
            self.assertEqual(cfg.WHITELIST_STOCKS, ["SH600000"])
            self.assertTrue(cfg.is_whitelist_configured())


if __name__ == "__main__":
    unittest.main(verbosity=2)
