"""ReportGenerationNode：复用 llm_reporter.py 生成 7 板块 AI 日报（含数据质量提示）。

use_llm=True 走 AI 日报（mock 或真实模型）；False 走规则版 report.py。
"""
from __future__ import annotations

from typing import Any

from ..agent_state import AgentState
from ..llm_reporter import generate_ai_report
from ..report import build_report
from ._common import make_step


def report_generation_node(state: AgentState) -> dict[str, Any]:
    analysis = state.get("analysis_result")
    if not analysis:  # 上游失败，给出明确说明而非空报告
        return {
            "report_markdown": "",
            "report_mode": "error",
            "llm_mode": "error",
            "steps": [make_step("AI 日报生成", "无分析结果，已跳过", status="error")],
        }
    use_llm = state.get("use_llm", True)
    try:
        if use_llm:
            md, mode = generate_ai_report(analysis, force_mock=state.get("force_mock", False))
        else:
            md, mode = build_report(analysis), "rule"
        return {
            "report_markdown": md,
            "report_mode": mode,
            "llm_mode": mode,
            "steps": [make_step("AI 日报生成", f"{mode} 模式")],
        }
    except Exception as e:  # noqa: BLE001
        return {
            "errors": [f"日报生成失败：{e}"],
            "report_mode": "error",
            "steps": [make_step("AI 日报生成", str(e), status="error")],
        }
