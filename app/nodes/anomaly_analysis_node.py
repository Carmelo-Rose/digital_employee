"""AnomalyAnalysisNode：复用 analyzer.py 的规则分析（已付款未发货 / 物流 / 退款 /
库存 / 客服关键词 / 订单金额异常），不重复实现逻辑。"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..agent_state import AgentState
from ..analyzer import analyze_orders
from ..memory import effective_config, get_field_overrides
from ._common import make_step


def anomaly_analysis_node(state: AgentState) -> dict[str, Any]:
    records = state.get("dataframe_records")
    if not records:  # 上游失败，跳过
        return {}
    try:
        df = pd.DataFrame(records)
        # 叠加业务规则记忆：字段映射纠正 + 阈值持久化
        cfg = effective_config()
        overrides = get_field_overrides()
        analysis = analyze_orders(df, cfg, field_overrides=overrides)
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
