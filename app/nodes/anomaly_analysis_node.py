"""AnomalyAnalysisNode：通过业务域 run_checks() 做异常检测，与具体业务解耦。"""
from __future__ import annotations

from typing import Any
from datetime import datetime

import pandas as pd

from ..agent_state import AgentState
from ..domains import get_domain
from ..memory import effective_config, get_field_overrides
from ._common import make_step


def _normalize_df(
    df: pd.DataFrame,
    aliases: dict[str, list[str]],
    time_cols: set[str],
    numeric_cols: set[str],
    overrides: dict[str, str] | None,
) -> pd.DataFrame:
    """把原始 df 规整为 canonical 列名，并做时间/数值列类型转换。"""
    lookup = {str(c).strip().lower(): c for c in df.columns}
    col_map: dict[str, str] = {}
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            if alias.lower() in lookup:
                col_map[canonical] = lookup[alias.lower()]
                break
    if overrides:
        for raw_lower, canonical in overrides.items():
            if canonical and raw_lower in lookup:
                col_map[canonical] = lookup[raw_lower]

    out = pd.DataFrame()
    for canonical, original in col_map.items():
        out[canonical] = df[original]

    for col in time_cols & set(out.columns):
        out[col] = pd.to_datetime(out[col], errors="coerce")
    for col in numeric_cols & set(out.columns):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in set(out.columns) - time_cols - numeric_cols:
        out[col] = out[col].fillna("").astype(str).str.strip()
    return out


def anomaly_analysis_node(state: AgentState) -> dict[str, Any]:
    records = state.get("dataframe_records")
    if not records:  # 上游失败，跳过
        return {}
    try:
        domain_name = state.get("domain_name") or "ecommerce"
        domain = get_domain(domain_name)
        cfg = effective_config()
        overrides = get_field_overrides()

        raw_df = pd.DataFrame(records)

        # 通用域不做列名规整，直接用原始列名
        if domain_name == "general" or not domain.column_aliases:
            ndf = raw_df.copy()
        else:
            ndf = _normalize_df(
                raw_df,
                domain.column_aliases,
                domain.time_columns,
                domain.numeric_columns,
                overrides,
            )

        results = domain.run_checks(ndf, cfg)
        now = datetime.now()
        analysis = domain.build_analysis_dict(results, len(ndf), now)

        # 补全字段映射信息（report 层 data_quality_md 需要）
        analysis["recognized_columns"] = state.get("recognized_fields", [])
        analysis["unrecognized_columns"] = state.get("unrecognized_fields", [])
        analysis["key_missing"] = [
            domain.canonical_labels.get(f, f)
            for f in domain.key_fields
            if f not in ndf.columns
        ]

        detail = (
            f"共 {analysis['total_orders']} 单，"
            f"异常订单 {analysis.get('anomaly_orders', 0)} 单"
        )
        return {"analysis_result": analysis, "steps": [make_step("异常分析", detail)]}
    except Exception as e:  # noqa: BLE001
        return {
            "errors": [f"异常分析失败：{e}"],
            "steps": [make_step("异常分析", str(e), status="error")],
        }
