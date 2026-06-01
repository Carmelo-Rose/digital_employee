"""DataQualityNode：在字段映射之上做「值层面」质量检查。

检查：关键字段是否缺失、订单号是否为空、金额/付款时间是否可解析、库存字段是否存在。
注意：库存字段缺失时明确提示「未识别库存字段，本次未进行库存风险分析」，不误报无风险。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..agent_state import AgentState
from ..schema import CANONICAL_LABELS
from ._common import make_step

# DataQualityNode 关注的关键字段（canonical）
KEY_FIELDS = [
    "order_id", "product_name", "amount", "pay_status",
    "ship_status", "logistics_status", "refund_status", "cs_note",
]


def _label(c: str) -> str:
    return CANONICAL_LABELS.get(c, c)


def _is_blank(v: Any) -> bool:
    """None / NaN / NaT / 空串都视为「空值」，不计入「无法解析」。"""
    try:
        if v is None or pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return str(v).strip() == ""


def _unparseable(records: list[dict], col: str, kind: str) -> int:
    bad = 0
    for r in records:
        v = r.get(col)
        if _is_blank(v):
            continue
        try:
            if kind == "number":
                float(v)
            else:  # time
                if pd.isna(pd.to_datetime(v, errors="coerce")):
                    bad += 1
        except (ValueError, TypeError):
            bad += 1
    return bad


def data_quality_node(state: AgentState) -> dict[str, Any]:
    recognized = set(state.get("recognized_fields", []))
    if not recognized and not state.get("raw_columns"):
        return {}  # 上游失败，跳过

    mapped = state.get("mapped_columns", {})
    records = state.get("dataframe_records", [])

    key_missing = [c for c in KEY_FIELDS if c not in recognized]
    stock_present = "stock" in recognized

    checks: list[dict[str, Any]] = []
    issues: list[str] = []

    if "order_id" in mapped:
        col = mapped["order_id"]
        empty = sum(1 for r in records if _is_blank(r.get(col)))
        checks.append({"项": "订单号非空", "结果": f"{empty} 行为空" if empty else "通过"})
        if empty:
            issues.append(f"订单号 {empty} 行为空")

    if "amount" in mapped:
        bad = _unparseable(records, mapped["amount"], "number")
        checks.append({"项": "金额可解析", "结果": f"{bad} 行无法解析" if bad else "通过"})
        if bad:
            issues.append(f"金额 {bad} 行无法解析")

    if "pay_time" in mapped:
        bad = _unparseable(records, mapped["pay_time"], "time")
        checks.append({"项": "付款时间可解析", "结果": f"{bad} 行无法解析" if bad else "通过"})
        if bad:
            issues.append(f"付款时间 {bad} 行无法解析")

    notes: list[str] = []
    if not stock_present:
        notes.append("未识别库存字段，本次未进行库存风险分析")
        issues.append("库存字段缺失")
    if key_missing:
        issues.append("关键字段缺失：" + "、".join(_label(c) for c in key_missing))

    data_quality = {
        "recognized_fields": list(recognized),
        "unrecognized_fields": state.get("unrecognized_fields", []),
        "key_missing": [_label(c) for c in key_missing],
        "stock_field_present": stock_present,
        "checks": checks,
        "notes": notes,
    }
    detail = "；".join(issues) if issues else "关键字段齐全，数据质量良好"
    return {
        "data_quality": data_quality,
        "steps": [make_step("数据质量检查", detail)],
    }
