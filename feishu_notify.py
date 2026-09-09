"""
飞书通知模块 — 通过 Webhook 推送因子分析和选股结果
支持本地 CLI 调用方式，兼容环境变量配置
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# Webhook URL 和项目名称统一从 config 模块读取
from config import FEISHU_WEBHOOK_URL, FEISHU_PROJECT_NAME

PROJECT_NAME = FEISHU_PROJECT_NAME

# 飞书推送参数
FEISHU_TIMEOUT_SEC = 10          # Webhook 请求超时（秒）
FEISHU_FID_TRUNC_LEN = 20        # factor_id 显示截断长度

# CLI 入口需要的依赖
import pandas as pd


def _build_payload(text: str) -> dict:
    """构建飞书消息体"""
    return {
        "msg_type": "text",
        "content": {
            "text": f"[{PROJECT_NAME}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{text}"
        },
    }


def send_feishu(text: str, verbose: bool = True) -> bool:
    """
    发送文本消息到飞书 Webhook。

    Args:
        text:    消息正文
        verbose: 是否在控制台打印发送状态

    Returns:
        True 表示发送成功或跳过，False 表示发送失败
    """
    webhook_url = FEISHU_WEBHOOK_URL.strip()
    if not webhook_url or "YOUR_WEBHOOK" in webhook_url:
        if verbose:
            print("⚠️  飞书 Webhook 未配置，跳过推送", flush=True)
        return True

    payload = json.dumps(_build_payload(text)).encode("utf-8")

    try:
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=FEISHU_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            if result.get("code") != 0:
                print(f"⚠️  飞书 API 返回错误: {result}", flush=True)
                return False
            if verbose:
                print("✅ 飞书推送成功", flush=True)
            return True
    except Exception as e:
        print(f"⚠️  飞书推送失败: {e}", flush=True)
        return False


def send_ic_results(ic_df, top_n: int = 10) -> bool:
    """
    推送 IC 因子分析结果到飞书。

    Args:
        ic_df:   IC 分析结果 DataFrame
        top_n:   展示前 N 个因子

    Returns:
        发送是否成功
    """
    top = ic_df.head(top_n)
    lines = [f"📊 **因子 IC 分析完成** (共 {len(ic_df)} 个因子)", ""]

    for rank, (_, row) in enumerate(top.iterrows(), 1):
        fid = row["factor_id"][:FEISHU_FID_TRUNC_LEN]
        ic = row["IC_5d"]
        t = row["IC_t_5d"]
        pos = row["IC_pos_5d"]
        n = int(row["n_days"])
        icon = "🟢" if ic > 0 else "🔴"
        lines.append(f"{icon} #{rank} {fid}")
        lines.append(f"   IC={ic:+.4f}  t={t:+.2f}  正占比={pos:.1%}  天数={n}")

    lines += [
        "",
        f"💾 完整结果: ic_scan_results_new.csv",
        f"📅 数据截止: 2026-09-03",
    ]

    return send_feishu("\n".join(lines))


def send_top_stocks(stocks_df, top_n: int = 10) -> bool:
    """
    推送 Top N 选股结果到飞书。

    Args:
        stocks_df: 选股结果 DataFrame
        top_n:     展示前 N 只股票

    Returns:
        发送是否成功
    """
    top = stocks_df.head(top_n)
    lines = [f"🎯 **Top {top_n} 选股结果**", ""]

    for _, row in top.iterrows():
        rank = int(row["rank"])
        code = row["instrument"]
        score = row["composite_score"]
        lines.append(f"#{rank} {code}  综合得分={score:.3f}")

    lines += [
        "",
        "💡 筛选条件：最强因子 Top N 综合排序",
        f"💾 完整结果: top10_stocks_new.csv",
        f"📅 计算时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]

    return send_feishu("\n".join(lines))


def send_combined_report(ic_df, stocks_df, top_n: int = 10) -> bool:
    """
    推送完整的分析报告（IC + 选股）到飞书。

    Args:
        ic_df:     IC 分析结果 DataFrame
        stocks_df: 选股结果 DataFrame
        top_n:     展示数量

    Returns:
        发送是否成功
    """
    parts = []

    # 标题
    parts.append(f"📈 **RD-Agent 因子分析与选股报告**")
    parts.append(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    parts.append("")

    # IC 结果摘要
    parts.append("━━━ 📊 因子 IC 分析 ━━━")
    parts.append(f"分析因子数: {len(ic_df)}")
    parts.append(f"有效交易日: {int(ic_df['n_days'].mean())} 天")
    parts.append(f"平均 |IC|:  {ic_df['IC_5d'].abs().mean():.4f}")
    parts.append("")
    parts.append("**Top 5 因子:**")
    for rank, (_, row) in enumerate(ic_df.head(5).iterrows(), 1):
        icon = "🟢" if row["IC_5d"] > 0 else "🔴"
        parts.append(
            f"  {icon} #{rank} {row['factor_id'][:30]}  IC={row['IC_5d']:+.4f}  t={row['IC_t_5d']:.1f}"
        )

    parts.append("")
    parts.append("━━━ 🎯 Top 10 选股 ━━━")
    for _, row in stocks_df.head(10).iterrows():
        parts.append(f"  {int(row['rank']):2d}. {row['instrument']}  得分={row['composite_score']:.3f}")

    parts.append("")
    parts.append("💾 数据文件:")
    parts.append("  - ic_scan_results_new.csv")
    parts.append("  - top10_stocks_new.csv")

    return send_feishu("\n".join(parts))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="飞书通知 CLI")
    parser.add_argument("--ic-results", help="IC 结果 CSV 路径")
    parser.add_argument("--stocks", help="选股结果 CSV 路径")
    parser.add_argument("--text", help="自定义文本消息")
    parser.add_argument("--top-n", type=int, default=10, help="展示数量")
    parser.add_argument("--url", help="飞书 Webhook URL（覆盖环境变量）")
    args = parser.parse_args()

    if args.url:
        import feishu_notify
        feishu_notify.FEISHU_WEBHOOK_URL = args.url

    if args.text:
        send_feishu(args.text)
    elif args.ic_results and args.stocks:
        ic_df = pd.read_csv(args.ic_results)
        stocks_df = pd.read_csv(args.stocks)
        send_combined_report(ic_df, stocks_df, args.top_n)
    elif args.ic_results:
        ic_df = pd.read_csv(args.ic_results)
        send_ic_results(ic_df, args.top_n)
    elif args.stocks:
        stocks_df = pd.read_csv(args.stocks)
        send_top_stocks(stocks_df, args.top_n)
    else:
        parser.print_help()
