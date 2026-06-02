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
    domain = get_domain(state.get("domain_name"))
    overrides = get_field_overrides()                              # 用户记忆的字段映射纠正
    resolved = _resolve_column_names(cols, domain.column_aliases, overrides)
    recognized = list(resolved.keys())
    used = set(resolved.values())
    unrecognized = [c for c in cols if c not in used]
    # 命中记忆的列单独点出来，让用户看到「上次纠正生效了」
    hit = sum(1 for raw in cols if str(raw).strip().lower() in (overrides or {}))
    detail = f"识别 {len(recognized)} 个标准字段，未识别 {len(unrecognized)} 个字段"
    if hit:
        detail += f"（含 {hit} 个来自记忆的映射纠正）"
    return {
        "mapped_columns": resolved,
        "recognized_fields": recognized,
        "unrecognized_fields": unrecognized,
        "steps": [make_step("字段映射", detail)],
    }
