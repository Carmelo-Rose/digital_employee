"""FieldMappingNode：把中文/英文表头映射成统一 canonical 字段。

通过 get_domain() 从业务域获取 column_aliases，与具体业务解耦。
"""
from __future__ import annotations

from typing import Any

from ..agent_state import AgentState
from ..domains import get_domain
from ..memory import get_field_overrides
from ._common import make_step


def _resolve_column_names(
    columns: list[str],
    aliases: dict[str, list[str]],
    overrides: dict[str, str] | None,
) -> dict[str, str]:
    """从列名列表解析 {canonical: 原始列名}，支持用户记忆覆盖。"""
    lookup = {str(c).strip().lower(): str(c) for c in columns}
    resolved: dict[str, str] = {}
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            if alias.lower() in lookup:
                resolved[canonical] = lookup[alias.lower()]
                break
    if overrides:
        for raw_lower, canonical in overrides.items():
            if canonical and raw_lower in lookup:
                resolved[canonical] = lookup[raw_lower]
    return resolved


def field_mapping_node(state: AgentState) -> dict[str, Any]:
    cols = state.get("raw_columns")
    if not cols:  # 上游解析失败，跳过
        return {}
    domain_name = state.get("domain_name") or "ecommerce"
    domain = get_domain(domain_name)

    # 先用 LLM/关键词推断（含 domain 隔离记忆覆盖）
    from ..field_infer import infer_fields
    from ..llm import get_llm_client
    from ..memory import get_field_overrides

    sample_rows = state.get("preview_rows") or []
    try:
        llm = get_llm_client()
        infer_result = infer_fields(cols, sample_rows[:3], llm_client=llm)
    except Exception:  # noqa: BLE001
        infer_result = infer_fields(cols, sample_rows[:3], llm_client=None)

    col_mapping: dict[str, str | None] = infer_result["column_mapping"]
    infer_method: str = infer_result["method"]
    # 用推断结果更新域（infer_fields 可能把 ecommerce/hr 纠正为 general）
    domain_name = infer_result.get("domain_name", domain_name)

    # 叠加用户记忆（最高优先级）
    overrides = get_field_overrides(domain_name)
    col_lookup = {str(c).strip().lower(): str(c) for c in cols}
    for raw_lower, canonical in overrides.items():
        if canonical and raw_lower in col_lookup:
            orig = col_lookup[raw_lower]
            col_mapping[orig] = canonical

    # 转为 {canonical: 原始列名}
    resolved: dict[str, str] = {v: k for k, v in col_mapping.items() if v}
    recognized = list(resolved.keys())
    used = set(resolved.values())
    unrecognized = [c for c in cols if c not in used]

    hit = sum(1 for raw in cols if str(raw).strip().lower() in (overrides or {}))
    if domain_name == "general":
        detail = (
            f"未匹配已知业务域，切换为通用数据质量分析"
            f"（共 {len(cols)} 列，推断方式：{infer_method}）"
        )
    else:
        detail = (
            f"识别 {len(recognized)} 个标准字段，未识别 {len(unrecognized)} 个字段"
            f"（推断方式：{infer_method}）"
        )
    if hit:
        detail += f"（含 {hit} 个来自记忆的映射纠正）"
    return {
        "domain_name": domain_name,
        "mapped_columns": resolved,
        "recognized_fields": recognized,
        "unrecognized_fields": unrecognized,
        "steps": [make_step("字段映射", detail)],
    }
