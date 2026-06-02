"""HumanReviewNode：人工确认节点（HITL interrupt），支持 4 种人工动作。

执行到此节点时调用 LangGraph interrupt()，图执行真正阻塞在此处。
checkpointer 将完整 state 序列化保存；外部通过 Command(resume=...) 恢复。

resume 值支持两种形态（向后兼容）：
  - 字符串 "approve" / "reject"          （旧调用）
  - dict   {"action": ..., "edited_markdown": ..., "feedback": ...}（新）

四种动作：
  approve  确认推送                    → 条件边路由到 wecom_push
  reject   拒绝，仅保存不推送          → 条件边路由到 END
  edit     人工改写日报后推送          → 用 edited_markdown 覆盖 report_markdown，再推送
  revise   给反馈让 AI 重写            → 写入 review_feedback，条件边路由回 report_generation
"""
from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from ..agent_state import AgentState
from ._common import make_step


def _parse_decision(decision: Any) -> tuple[str, str, str]:
    """把 resume 值归一成 (action, edited_markdown, feedback)。"""
    if isinstance(decision, str):
        return decision, "", ""
    if isinstance(decision, dict):
        return (
            str(decision.get("action", "approve")),
            str(decision.get("edited_markdown") or ""),
            str(decision.get("feedback") or ""),
        )
    return "approve", "", ""


def human_review_node(state: AgentState) -> dict[str, Any]:
    # 上游失败或报告为空则跳过等待，直接标记不需要审核
    if state.get("errors") or not state.get("report_markdown"):
        return {
            "need_human_review": False,
            "human_approved": False,
            "review_action": "skip",
        }

    # interrupt() 在此真正阻断图执行；
    # 传入的 dict 会原样作为 interrupt value 暴露给调用方（可携带摘要信息）。
    decision = interrupt({
        "action": "human_review",
        "message": "请预览日报后，确认 / 编辑 / 反馈重写 / 拒绝",
        "report_preview": (state.get("report_markdown") or "")[:500],
    })

    # 图被 Command(resume=...) 恢复后，interrupt() 返回 resume 传入的值
    action, edited_markdown, feedback = _parse_decision(decision)

    if action == "edit":
        new_md = edited_markdown or state.get("report_markdown", "")
        return {
            "review_action": "edit",
            "human_approved": True,
            "need_human_review": True,
            "report_markdown": new_md,          # 覆盖为人工编辑后的版本
            "steps": [make_step("人工审核", "已人工编辑日报，准备推送", status="done")],
        }

    if action == "revise":
        return {
            "review_action": "revise",
            "human_approved": False,
            "need_human_review": True,
            "review_feedback": feedback,        # 喂回 report_generation 重写
            "steps": [make_step("人工审核", f"已提交修改意见，AI 重写中：{feedback[:30]}", status="done")],
        }

    # approve / reject（含未知动作回退为 reject 语义）
    approved = action == "approve"
    return {
        "review_action": "approve" if approved else "reject",
        "human_approved": approved,
        "need_human_review": True,
        "steps": [make_step(
            "人工审核",
            "已批准，准备推送" if approved else "已拒绝，跳过推送",
            status="done",
        )],
    }
