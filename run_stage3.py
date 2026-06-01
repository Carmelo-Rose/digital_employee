#!/usr/bin/env python3
"""第三阶段命令行入口：订单文件 → 规则分析 → （可选）AI 日报 → （可选）推送企微。

示例：
    # 规则版日报
    python run_stage3.py --input data/sample_orders.xlsx --output reports/report.md

    # AI 数字员工日报（默认 mock，配了 MiMo/Claude Key 则走真实模型）
    python run_stage3.py --input data/sample_orders.xlsx --output reports/ai_report.md --use-llm

    # 生成 AI 日报并推送到企业微信（未配 webhook 时自动 mock）
    python run_stage3.py --input data/sample_orders.xlsx --output reports/ai_report.md --use-llm --send-wecom
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 保证从项目根目录外也能 import app.*
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.analyzer import analyze_orders          # noqa: E402
from app.llm_reporter import generate_ai_report  # noqa: E402
from app.loader import read_orders_table         # noqa: E402
from app.push import push_report                 # noqa: E402
from app.report import build_report              # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="电商运营数字员工 · 第三阶段 CLI")
    ap.add_argument("--input", required=True, help="输入订单文件（.xlsx/.xls/.csv）")
    ap.add_argument("--output", required=True, help="输出 Markdown 日报路径")
    ap.add_argument("--use-llm", action="store_true", help="生成 AI 风格日报（否则规则版）")
    ap.add_argument("--send-wecom", action="store_true", help="推送到企业微信（未配 webhook 时 mock）")
    ap.add_argument("--force-mock", action="store_true", help="强制 AI 日报走 mock，不调真实模型")
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"❌ 输入文件不存在：{in_path}", file=sys.stderr)
        return 1

    # 1) 读取 + 规则分析（保留第一/二阶段能力）
    print(f"📥 读取 {in_path} …")
    df = read_orders_table(in_path)
    analysis = analyze_orders(df)
    print(
        f"🔍 规则分析：共 {analysis['total_orders']} 单，"
        f"异常订单 {analysis.get('anomaly_orders', analysis['anomaly_total'])} 单 → {analysis['summary']}"
    )

    # 2) 生成日报：AI 版 or 规则版
    if args.use_llm:
        md, mode = generate_ai_report(analysis, force_mock=args.force_mock)
        print(f"🤖 已生成 AI 日报（模式：{mode}）")
    else:
        md = build_report(analysis)
        print("📝 已生成规则版日报")

    # 3) 写出
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"💾 日报已写入 {out_path}（{len(md)} 字符）")

    # 4) 可选推送（复用 app/push.py，未配 webhook 自动 mock）
    if args.send_wecom:
        result = push_report(md, channel="wecom")
        if result.get("ok"):
            tag = "（模拟）" if result.get("mock") else ""
            print(f"📤 企业微信推送成功{tag}")
        else:
            print(f"⚠️ 企业微信推送失败：{result.get('error')}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
