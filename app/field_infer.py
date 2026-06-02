"""LLM 字段语义推断。

给定表头列表 + 前几行样本，让 LLM 推断：
1. 业务域（domain_name）：ecommerce / hr / unknown
2. 每列对应的 canonical 字段（推断不出填 null）

LLM 不可用时，降级为关键词模糊匹配兜底。
"""
from __future__ import annotations

import json
import re
from typing import Any

from .domains import DOMAIN_REGISTRY, get_domain


# ── 关键词降级匹配 ─────────────────────────────────────────────────────────────

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "ecommerce": ["订单", "发货", "物流", "支付", "退款", "库存", "sku", "店铺", "快递"],
    "hr":        ["员工", "入职", "合同", "试用", "转正", "部门", "岗位", "离职", "工号"],
}
# 关键词命中数 < 阈值 → 退回通用域
_KEYWORD_THRESHOLD = 2
# 别名覆盖率 < 阈值 → 退回通用域
_COVERAGE_THRESHOLD = 0.30


def _fuzzy_match_domain(columns: list[str]) -> str:
    """基于关键词猜测业务域，LLM 不可用时使用。

    同时检查关键词命中数和字段别名覆盖率，两项都通过才确认域；
    否则返回 'general'，走通用数据质量分析路径。
    """
    col_str = " ".join(columns).lower()
    scores: dict[str, int] = {}
    for domain, kws in _DOMAIN_KEYWORDS.items():
        scores[domain] = sum(1 for kw in kws if kw in col_str)

    best = max(scores, key=lambda k: scores[k])
    if scores[best] < _KEYWORD_THRESHOLD:
        return "general"

    # 再检查别名覆盖率（避免 1 个关键词命中就强行归类）
    try:
        domain = get_domain(best)
        lookup: set[str] = set()
        for alias_list in domain.column_aliases.values():
            for alias in alias_list:
                lookup.add(alias.lower())
        matched = sum(
            1 for col in columns
            if any(a in col.lower() or col.lower() in a for a in lookup)
        )
        coverage = matched / len(columns) if columns else 0
        if coverage < _COVERAGE_THRESHOLD:
            return "general"
    except Exception:  # noqa: BLE001
        pass

    return best


def _fuzzy_match_columns(
    columns: list[str],
    domain_name: str,
) -> dict[str, str | None]:
    """扩展别名模糊匹配，LLM 不可用时兜底。返回 {原始列名: canonical | None}。"""
    try:
        domain = get_domain(domain_name)
    except ValueError:
        domain = get_domain("ecommerce")

    lookup: dict[str, str] = {}  # alias_lower -> canonical
    for canonical, aliases in domain.column_aliases.items():
        for alias in aliases:
            lookup[alias.lower()] = canonical

    result: dict[str, str | None] = {}
    for col in columns:
        col_lower = col.strip().lower()
        # 精确匹配
        if col_lower in lookup:
            result[col] = lookup[col_lower]
            continue
        # 包含匹配（较短的列名只要被别名包含，或别名被列名包含）
        matched = None
        for alias_lower, canonical in lookup.items():
            if alias_lower in col_lower or col_lower in alias_lower:
                matched = canonical
                break
        result[col] = matched
    return result


# ── LLM 推断 ─────────────────────────────────────────────────────────────────

def _build_infer_prompt(
    columns: list[str],
    sample_rows: list[dict[str, Any]],
    available_domains: dict[str, str],
) -> str:
    domains_desc = "\n".join(f"  - {k}: {v}" for k, v in available_domains.items())
    sample_str = json.dumps(sample_rows[:3], ensure_ascii=False, indent=2)
    return f"""你是数据结构分析专家，请分析以下表格，返回 JSON。

## 表头列名
{json.dumps(columns, ensure_ascii=False)}

## 前几行样本
{sample_str}

## 可选业务域
{domains_desc}

## 任务
1. 判断这是哪个业务域（domain_name 填上方列表的 key）
2. 为每个列名推断对应的 canonical 字段名（推断不出填 null）
   - 电商可选：order_id, store_name, pay_status, pay_time, ship_status, ship_time,
     logistics_status, logistics_update_time, refund_status, refund_apply_time,
     sku, product_name, quantity, stock, amount, cs_note
   - HR 可选：emp_id, emp_name, department, position, hire_date, contract_end,
     emp_status, probation_result, remark

## 输出格式（只输出 JSON，不要其他文字）
{{
  "domain_name": "<key>",
  "column_mapping": {{
    "<原始列名>": "<canonical 或 null>",
    ...
  }}
}}"""


def infer_fields(
    columns: list[str],
    sample_rows: list[dict[str, Any]],
    llm_client: Any = None,
) -> dict[str, Any]:
    """推断业务域和字段映射。

    返回：
    {
        "domain_name": str,          # 推断的业务域
        "column_mapping": {str: str|None},  # 原始列名 -> canonical
        "method": "llm" | "fuzzy",   # 使用的推断方式
    }
    """
    available_domains = {k: get_domain(k).name for k in DOMAIN_REGISTRY}

    # 尝试 LLM 推断
    if llm_client is not None:
        try:
            prompt = _build_infer_prompt(columns, sample_rows, available_domains)
            raw = llm_client.complete(prompt)
            # 提取 JSON（模型有时会在前后加说明文字）
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                parsed = json.loads(m.group())
                domain_name = parsed.get("domain_name", "general")
                if domain_name not in DOMAIN_REGISTRY:
                    domain_name = "general"
                mapping: dict[str, str | None] = {}
                for col in columns:
                    mapping[col] = parsed.get("column_mapping", {}).get(col)
                return {"domain_name": domain_name, "column_mapping": mapping, "method": "llm"}
        except Exception:  # noqa: BLE001
            pass

    # 降级：关键词匹配
    domain_name = _fuzzy_match_domain(columns)
    mapping = _fuzzy_match_columns(columns, domain_name)
    return {"domain_name": domain_name, "column_mapping": mapping, "method": "fuzzy"}
