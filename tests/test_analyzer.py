"""针对 sample_orders.csv 的异常检测单测。"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from app.analyzer import analyze_orders
from app.config import SAMPLE_CSV
from app.report import build_report

# 固定 now，让基于时间的阈值判断结果稳定
NOW = datetime(2026, 6, 1, 12, 0, 0)


@pytest.fixture
def analysis() -> dict:
    df = pd.read_csv(SAMPLE_CSV)
    return analyze_orders(df, now=NOW)


def test_totals(analysis):
    assert analysis["total_orders"] == 15
    assert analysis["anomaly_total"] > 0
    assert not analysis["skipped_checks"], "样例应能识别全部列"


def test_paid_not_shipped(analysis):
    items = analysis["categories"]["paid_not_shipped"]
    ids = {it["order_id"] for it in items}
    # 已付款且未发货/部分发货：001,002,007,012
    assert {"SO20260601001", "SO20260601002", "SO20260601007", "SO20260601012"} <= ids
    # 未付款的 009 不应入选
    assert "SO20260601009" not in ids


def test_logistics(analysis):
    ids = {it["order_id"] for it in analysis["categories"]["logistics_abnormal"]}
    assert {"SO20260601003", "SO20260601010"} <= ids  # 物流异常 / 超时


def test_refund(analysis):
    ids = {it["order_id"] for it in analysis["categories"]["refund_abnormal"]}
    assert {"SO20260601006", "SO20260601014"} <= ids  # 退款失败 / 退款异常


def test_low_stock(analysis):
    ids = {it["order_id"] for it in analysis["categories"]["low_stock"]}
    assert "SO20260601007" in ids  # 库存 0
    assert "SO20260601011" in ids  # 库存 4 < 数量 5


def test_cs_keyword(analysis):
    ids = {it["order_id"] for it in analysis["categories"]["cs_keyword"]}
    # 催发货/质量/投诉/差评假货
    assert {"SO20260601002", "SO20260601005", "SO20260601007", "SO20260601014"} <= ids


def test_missing_columns_skip():
    df = pd.DataFrame({"订单号": ["X1"], "库存": [0]})
    result = analyze_orders(df, now=NOW)
    assert result["summary"]["low_stock"] == 1
    assert any("已付款未发货" in s for s in result["skipped_checks"])


def test_report_renders(analysis):
    from app.llm import MockLLM
    md = build_report(analysis, llm=MockLLM())  # 用 mock，测试不依赖网络
    assert "电商运营日报" in md
    assert "智能洞察与建议" in md
    assert "已付款未发货" in md
