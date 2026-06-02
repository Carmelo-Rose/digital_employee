"""DataQualityNode：在字段映射之上做「值层面」质量检查。

检查项完全由业务域（BusinessDomain）决定，不硬编码电商字段：
- 关键字段缺失（domain.key_fields）
- 主键字段空值（domain 主键，即 key_fields 第一个字段）
- 数值列可解析（domain.numeric_columns）
- 时间列可解析（domain.time_columns）
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..agent_state import AgentState
from ..domains import get_domain
from ._common import make_step


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

    domain = get_domain(state.get("domain_name"))
    labels = domain.canonical_labels

    def _label(c: str) -> str:
        return labels.get(c, c)

    mapped = state.get("mapped_columns", {})
    records = state.get("dataframe_records", [])

    # 关键字段缺失检查（完全由业务域定义，不硬编码）
    key_missing = [c for c in domain.key_fields if c not in recognized]

    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    notes: list[str] = []

    # 主键空值检查（取 key_fields 第一个字段作为行级标识）
    primary_key = domain.key_fields[0] if domain.key_fields else None
    if primary_key and primary_key in mapped:
        col = mapped[primary_key]
        empty = sum(1 for r in records if _is_blank(r.get(col)))
        label = _label(primary_key)
        checks.append({"项": f"{label}非空", "结果": f"{empty} 行为空" if empty else "通过"})
        if empty:
            issues.append(f"{label} {empty} 行为空")

    # 数值列可解析（由 domain.numeric_columns 动态决定）
    for canonical in domain.numeric_columns:
        if canonical in mapped:
            bad = _unparseable(records, mapped[canonical], "number")
            label = _label(canonical)
            checks.append({"项": f"{label}可解析", "结果": f"{bad} 行无法解析" if bad else "通过"})
            if bad:
                issues.append(f"{label} {bad} 行无法解析")

    # 时间列可解析（由 domain.time_columns 动态决定）
    for canonical in domain.time_columns:
        if canonical in mapped:
            bad = _unparseable(records, mapped[canonical], "time")
            label = _label(canonical)
            checks.append({"项": f"{label}可解析", "结果": f"{bad} 行无法解析" if bad else "通过"})
            if bad:
                issues.append(f"{label} {bad} 行无法解析")

    # 跳过检测提示（未识别字段）
    for canonical in domain.key_fields:
        if canonical not in recognized:
            notes.append(f"未识别「{_label(canonical)}」字段，依赖该字段的检测已跳过")

    if key_missing:
        issues.append("关键字段缺失：" + "、".join(_label(c) for c in key_missing))

    data_quality = {
        "recognized_fields": list(recognized),
        "unrecognized_fields": state.get("unrecognized_fields", []),
        "key_missing": [_label(c) for c in key_missing],
        "checks": checks,
        "notes": notes,
    }
    detail = "；".join(issues) if issues else "关键字段齐全，数据质量良好"
    return {
        "data_quality": data_quality,
        "steps": [make_step("数据质量检查", detail)],
    }
