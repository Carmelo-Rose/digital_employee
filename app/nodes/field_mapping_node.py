"""FieldMappingNode：把中文/英文表头映射成统一 canonical 字段。

复用 schema.resolve_column_names，支持订单号/order_id、店铺名称/store_name 等。
"""
from __future__ import annotations

from typing import Any

from ..agent_state import AgentState
from ..memory import get_field_overrides
from ..schema import resolve_column_names
from ._common import make_step


def field_mapping_node(state: AgentState) -> dict[str, Any]:
    cols = state.get("raw_columns")
    if not cols:  # 上游解析失败，跳过
        return {}
    overrides = get_field_overrides()                   # 用户记忆的字段映射纠正
    resolved = resolve_column_names(cols, overrides)    # canonical -> 原始列名
    recognized = list(resolved.keys())
    used = set(resolved.values())
    unrecognized = [c for c in cols if c not in used]
    # 命中记忆的列单独点出来，让用户看到「上次纠正生效了」
    hit = sum(1 for raw in cols if str(raw).strip().lower() in overrides)
    detail = f"识别 {len(recognized)} 个标准字段，未识别 {len(unrecognized)} 个字段"
    if hit:
        detail += f"（含 {hit} 个来自记忆的映射纠正）"
    return {
        "mapped_columns": resolved,
        "recognized_fields": recognized,
        "unrecognized_fields": unrecognized,
        "steps": [make_step("字段映射", detail)],
    }
