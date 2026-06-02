"""ReportGenerationNode：通过业务域生成 AI 日报（mock 或真实 LLM）。

use_llm=True 走 AI 日报；False 走规则版 report.py（仅电商域支持）。
"""
from __future__ import annotations

from typing import Any

from ..agent_state import AgentState
from ..config import settings
from ..domains import get_domain
from ..llm import AnthropicLLM, get_llm_client
from ..report import build_report, data_quality_md
from ._common import make_step


def _generate_report(
    analysis: dict,
    domain_name: str | None,
    *,
    force_mock: bool = False,
    feedback: str | None = None,
) -> tuple[str, str]:
    """调用业务域的 LLM 日报生成逻辑，返回 (markdown, mode)。

    流程：
      1. 检查是否有真实 LLM 可用（provider + key）。
      2. 无真实 LLM → 调用 domain.build_mock_report()。
      3. 有真实 LLM → 用 domain.get_system_prompt() 调模型，失败回退 mock。
    """
    domain = get_domain(domain_name)
    cfg = settings
    provider = cfg.llm_provider.lower()
    want_real = (not force_mock) and provider in {"mimo", "claude", "anthropic"} and bool(cfg.llm_api_key)

    if not want_real:
        md = domain.build_mock_report(analysis)
        if feedback:
            note = f"> 已采纳人工修改意见：{feedback}\n>（mock 模式不调真实模型）\n\n"
            lines = md.split("\n", 2)
            md = (lines[0] + "\n\n" + note + "\n".join(lines[1:])) if len(lines) > 1 else note + md
        return md, "mock"

    client = get_llm_client(cfg)
    if not (isinstance(client, AnthropicLLM) and client.available):
        return domain.build_mock_report(analysis), "mock"

    try:
        prompt = _build_prompt(analysis)
        if feedback:
            prompt += (
                f"\n\n【运营负责人对上一版日报的修改意见】\n{feedback}\n"
                "请在保持板块结构的前提下，按此意见重写日报。"
            )
        body = client.complete(prompt, system=domain.get_system_prompt())
        if not body.strip():
            return domain.build_mock_report(analysis), "mock"
        header = f"# AI 日报 · {analysis['date']}\n\n> 由 {cfg.llm_model} 生成\n"
        return f"{header}\n{body}\n\n{data_quality_md(analysis)}", "llm"
    except Exception as e:  # noqa: BLE001
        return domain.build_mock_report(analysis) + f"\n\n> _（实时生成失败，已回退 mock：{e}）_", "mock"


def _build_prompt(analysis: dict) -> str:
    """把分析结果压成紧凑文本喂给模型。"""
    titles = analysis["category_titles"]
    lines = [
        f"日期：{analysis['date']}",
        f"订单总数：{analysis['total_orders']}",
        f"异常订单数（去重）：{analysis.get('anomaly_orders', analysis['anomaly_total'])}",
        "",
        "各类异常计数与样例：",
    ]
    for key, title in titles.items():
        items = analysis["categories"].get(key, [])
        if not items:
            lines.append(f"- {title}：0")
            continue
        ex = "；".join(
            f"{it.get('record_id') or it.get('order_id', '')}（{it['原因']}）"
            for it in items[:5]
        )
        lines.append(f"- {title}：{len(items)}，例：{ex}")
    severe = [
        it for items in analysis["categories"].values()
        for it in items if it.get("严重度") == "严重"
    ]
    if severe:
        lines += ["", "严重级订单（建议优先处理）："]
        lines.extend(
            f"- {s.get('record_id') or s.get('order_id', '')}｜{s['原因']}"
            for s in severe[:15]
        )
    if analysis.get("skipped_checks"):
        lines += ["", "以下检测因缺列被跳过：" + "；".join(analysis["skipped_checks"])]
    return "\n".join(lines)


def report_generation_node(state: AgentState) -> dict[str, Any]:
    analysis = state.get("analysis_result")
    if not analysis:
        return {
            "report_markdown": "",
            "report_mode": "error",
            "llm_mode": "error",
            "steps": [make_step("AI 日报生成", "无分析结果，已跳过", status="error")],
        }
    use_llm = state.get("use_llm", True)
    feedback = state.get("review_feedback") or ""
    is_revise = state.get("review_action") == "revise" and bool(feedback)
    try:
        if use_llm:
            md, mode = _generate_report(
                analysis,
                state.get("domain_name"),
                force_mock=state.get("force_mock", False),
                feedback=feedback or None,
            )
        else:
            # use_llm=False: 用 domain 的 mock 模板渲染，保持多业务域兼容
            # 电商域 fallback 到 build_report() 维持规则版格式，其他域用 build_mock_report
            from ..domains import get_domain as _gd
            _domain = _gd(state.get("domain_name"))
            if state.get("domain_name", "ecommerce") == "ecommerce":
                md, mode = build_report(analysis), "rule"
            else:
                md, mode = _domain.build_mock_report(analysis), "mock"
        detail = f"{mode} 模式" + ("（按人工意见重写）" if is_revise else "")
        return {
            "report_markdown": md,
            "report_mode": mode,
            "llm_mode": mode,
            "review_feedback": "",
            "steps": [make_step("AI 日报生成", detail)],
        }
    except Exception as e:  # noqa: BLE001
        return {
            "errors": [f"日报生成失败：{e}"],
            "report_mode": "error",
            "steps": [make_step("AI 日报生成", str(e), status="error")],
        }
