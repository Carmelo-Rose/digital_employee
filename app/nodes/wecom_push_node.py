"""WecomPushNode：复用 wecom_sender.py 推送企业微信。

仅当 human_approved 且 send_wecom 为真时才推送。状态：
- skipped         未确认 / 未开启推送
- success         真实推送成功
- missing_webhook 未配置 WECOM_WEBHOOK_URL（走模拟，不崩溃）
- failed          推送失败
"""
from __future__ import annotations

from typing import Any

from ..agent_state import AgentState
from ..wecom_sender import send_to_wecom
from ._common import make_step


def wecom_push_node(state: AgentState) -> dict[str, Any]:
    md = state.get("report_markdown", "") or ""

    if not (state.get("human_approved") and state.get("send_wecom")):
        res = {"status": "skipped", "message": "未确认或未开启推送，已跳过"}
        return {"wecom_result": res, "steps": [make_step("企业微信推送", "已跳过", status="done")]}

    if not md.strip():
        res = {"status": "failed", "message": "日报为空，无法推送"}
        return {"wecom_result": res, "steps": [make_step("企业微信推送", res["message"], status="error")]}

    analysis = state.get("analysis_result") or {}
    raw = send_to_wecom(md, analysis=analysis)  # {ok, mock?, message?, error?, response?}
    if raw.get("ok") and raw.get("mock"):
        status, detail, st = "missing_webhook", raw.get("message", "未配置 webhook，已模拟推送"), "done"
    elif raw.get("ok"):
        status, detail, st = "success", "已推送到企业微信", "done"
    else:
        status, detail, st = "failed", raw.get("error", "推送失败"), "error"

    res = {"status": status, **raw}
    return {"wecom_result": res, "steps": [make_step("企业微信推送", detail, status=st)]}
