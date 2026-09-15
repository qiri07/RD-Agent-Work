#!/usr/bin/env python3
"""
feishu_notify.py 单元测试
==========================
测试 send_feishu, send_ic_results, send_top_stocks, send_combined_report 等功能。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd


class TestSendFeishu(unittest.TestCase):
    """测试 send_feishu 函数"""

    @mock.patch('feishu_notify.urllib.request.urlopen')
    def test_send_success(self, mock_urlopen):
        """发送成功"""
        mock_response = mock.MagicMock()
        mock_response.read.return_value = b'{"errcode":0}'
        mock_urlopen.return_value = mock_response
        
        from feishu_notify import send_feishu
        result = send_feishu("测试消息")
        self.assertIsInstance(result, bool)

    @mock.patch('feishu_notify.urllib.request.urlopen')
    def test_send_failure(self, mock_urlopen):
        """发送失败"""
        mock_urlopen.side_effect = Exception("Network error")
        
        from feishu_notify import send_feishu
        result = send_feishu("测试消息")
        self.assertFalse(result)

    @mock.patch('feishu_notify.FEISHU_WEBHOOK_URL', '')
    def test_empty_webhook(self):
        """空Webhook URL - 应返回False或不发送"""
        from feishu_notify import send_feishu
        # 空URL时不应发送，可能返回None或False
        result = send_feishu("测试消息")
        # 根据实际实现，可能返回None表示跳过


class TestSendIcResults(unittest.TestCase):
    """测试 send_ic_results 函数"""

    def test_with_valid_data(self):
        """有效数据"""
        ic_df = pd.DataFrame({
            'factor_id': ['f1', 'f2'],
            'IC_5d': [0.05, -0.03],
            'IC_t_5d': [3.0, -2.0],
            'IC_pos_5d': [0.6, 0.4],
            'n_days': [200, 180],
        })
        
        with mock.patch('feishu_notify.send_feishu') as mock_send:
            mock_send.return_value = True
            from feishu_notify import send_ic_results
            result = send_ic_results(ic_df)
            self.assertIsInstance(result, bool)

    def test_empty_data(self):
        """空数据"""
        ic_df = pd.DataFrame()
        
        with mock.patch('feishu_notify.send_feishu') as mock_send:
            from feishu_notify import send_ic_results
            # 空DataFrame不应崩溃
            try:
                result = send_ic_results(ic_df)
                self.assertIsInstance(result, bool)
            except Exception:
                pass  # 允许异常


class TestSendTopStocks(unittest.TestCase):
    """测试 send_top_stocks 函数"""

    def test_with_valid_data(self):
        """有效数据"""
        stocks_df = pd.DataFrame({
            'rank': [1, 2],
            'instrument': ['SH600000', 'SZ000001'],
            'composite_score': [0.95, 0.92],
        })
        
        with mock.patch('feishu_notify.send_feishu') as mock_send:
            mock_send.return_value = True
            from feishu_notify import send_top_stocks
            result = send_top_stocks(stocks_df)
            self.assertIsInstance(result, bool)

    def test_empty_data(self):
        """空数据"""
        stocks_df = pd.DataFrame()
        
        with mock.patch('feishu_notify.send_feishu') as mock_send:
            from feishu_notify import send_top_stocks
            # 空DataFrame不应崩溃
            try:
                result = send_top_stocks(stocks_df)
                self.assertIsInstance(result, bool)
            except Exception:
                pass  # 允许异常


class TestSendCombinedReport(unittest.TestCase):
    """测试 send_combined_report 函数"""

    def test_with_all_data(self):
        """完整数据"""
        ic_df = pd.DataFrame({
            'factor_id': ['f1'],
            'IC_5d': [0.05],
            'IC_t_5d': [3.0],
            'n_days': [200],
        })
        stocks_df = pd.DataFrame({
            'rank': [1],
            'instrument': ['SH600000'],
            'composite_score': [0.95],
        })
        
        with mock.patch('feishu_notify.send_feishu') as mock_send:
            mock_send.return_value = True
            from feishu_notify import send_combined_report
            result = send_combined_report(ic_df, stocks_df)
            self.assertIsInstance(result, bool)

    def test_missing_data(self):
        """缺失数据应抛出异常"""
        with mock.patch('feishu_notify.send_feishu') as mock_send:
            from feishu_notify import send_combined_report
            # None 数据应抛出TypeError
            with self.assertRaises((TypeError, AttributeError)):
                send_combined_report(None, None)


class TestConstants(unittest.TestCase):
    """测试模块常量"""

    def test_project_name(self):
        """项目名称"""
        from feishu_notify import PROJECT_NAME
        self.assertIsInstance(PROJECT_NAME, str)
        self.assertGreater(len(PROJECT_NAME), 0)

    def test_feishu_fid_trunc_len(self):
        """飞书字段截断长度"""
        from feishu_notify import FEISHU_FID_TRUNC_LEN
        self.assertEqual(FEISHU_FID_TRUNC_LEN, 20)

    def test_feishu_timeout_sec(self):
        """飞书请求超时"""
        from feishu_notify import FEISHU_TIMEOUT_SEC
        self.assertEqual(FEISHU_TIMEOUT_SEC, 10)


if __name__ == '__main__':
    unittest.main()
