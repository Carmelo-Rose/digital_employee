"""HumanReviewNode：人工确认节点。

第一段分析流程跑到这里就停（END），只设置「等待人工确认」状态，不直接推送。
真正的确认发生在 Web 页面点击「确认并推送到企业微信」后，由 wecom 流程接力。
"""
from __future__ import annotations

from typing import Any

from ..agent_state import AgentState
from ._common import make_step


def human_review_node(state: AgentState) -> dict[str, Any]:
    # 上游已失败则不进入等待确认
    if state.get("errors") or not state.get("report_markdown"):
        return {"need_human_review": False, "human_approved": False}
    return {
        "need_human_review": True,
        "human_approved": False,
        "steps": [make_step(
            "等待人工确认",
            "请预览日报后，确认是否推送到企业微信",
            status="waiting",
        )],
    }
