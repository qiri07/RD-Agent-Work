#!/usr/bin/env python3
"""
feishu_notify.py 单元测试 — 不发送网络请求
"""
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def reload_modules():
    for mod in list(sys.modules.keys()):
        if mod in ("config", "feishu_notify"):
            del sys.modules[mod]


class TestBuildPayload(unittest.TestCase):
    def setUp(self):
        reload_modules()
        import config as cfg
        cfg.FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
        cfg.FEISHU_PROJECT_NAME = "TestProject"

    def test_payload_structure(self):
        from feishu_notify import _build_payload
        payload = _build_payload("Hello")
        self.assertEqual(payload["msg_type"], "text")
        self.assertIn("Hello", payload["content"]["text"])
        self.assertIn("[TestProject]", payload["content"]["text"])

    def test_payload_has_timestamp(self):
        from feishu_notify import _build_payload
        payload = _build_payload("test")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.assertIn(now_str, payload["content"]["text"])


class TestSendFeishuSkip(unittest.TestCase):
    def test_skip_no_webhook(self):
        reload_modules()
        import config as cfg
        cfg.FEISHU_WEBHOOK_URL = ""
        from feishu_notify import send_feishu
        result = send_feishu("test", verbose=False)
        self.assertTrue(result)

    def test_skip_placeholder(self):
        reload_modules()
        import config as cfg
        cfg.FEISHU_WEBHOOK_URL = "YOUR_WEBHOOK"
        from feishu_notify import send_feishu
        result = send_feishu("test", verbose=False)
        self.assertTrue(result)


class TestSendICResults(unittest.TestCase):
    def test_message_content(self):
        reload_modules()
        import config as cfg
        cfg.FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
        cfg.FEISHU_PROJECT_NAME = "RD-Agent"

        from feishu_notify import send_ic_results
        ic_df = pd.DataFrame({
            "factor_id": ["momentum_5d", "volume_spike"],
            "IC_5d": [0.05, -0.03],
            "IC_t_5d": [3.2, -2.1],
            "IC_pos_5d": [0.6, 0.4],
            "n_days": [200, 180],
        })
        with mock.patch("feishu_notify.send_feishu") as mock_send:
            mock_send.return_value = True
            send_ic_results(ic_df, top_n=2)
            mock_send.assert_called_once()
            text = mock_send.call_args[0][0]
            self.assertIn("因子 IC 分析完成", text)
            self.assertIn("momentum_5d", text)


class TestSendTopStocks(unittest.TestCase):
    def test_message_content(self):
        reload_modules()
        import config as cfg
        cfg.FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
        cfg.FEISHU_PROJECT_NAME = "RD-Agent"

        from feishu_notify import send_top_stocks
        stocks_df = pd.DataFrame({
            "rank": [1, 2],
            "instrument": ["SH600653", "SH600651"],
            "composite_score": [4.37, 1.79],
        })
        with mock.patch("feishu_notify.send_feishu") as mock_send:
            mock_send.return_value = True
            send_top_stocks(stocks_df, top_n=2)
            mock_send.assert_called_once()
            text = mock_send.call_args[0][0]
            self.assertIn("SH600653", text)
            self.assertIn("综合得分", text)


class TestSendCombinedReport(unittest.TestCase):
    def test_message_content(self):
        reload_modules()
        import config as cfg
        cfg.FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
        cfg.FEISHU_PROJECT_NAME = "RD-Agent"

        from feishu_notify import send_combined_report
        ic_df = pd.DataFrame({
            "factor_id": ["f1", "f2"],
            "IC_5d": [0.05, -0.03],
            "IC_t_5d": [3.2, -2.1],
            "IC_pos_5d": [0.6, 0.4],
            "n_days": [200, 180],
        })
        stocks_df = pd.DataFrame({
            "rank": [1],
            "instrument": ["SH600653"],
            "composite_score": [4.37],
        })
        with mock.patch("feishu_notify.send_feishu") as mock_send:
            mock_send.return_value = True
            send_combined_report(ic_df, stocks_df, top_n=1)
            mock_send.assert_called_once()
            text = mock_send.call_args[0][0]
            self.assertIn("RD-Agent 因子分析与选股报告", text)
            self.assertIn("SH600653", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
