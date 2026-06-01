"""LangGraph 数字员工工作流编排。

两段图（避免第一版条件边复杂，逻辑更清晰）：
- 分析流程：START → file_parse → field_mapping → data_quality
                  → anomaly_analysis → report_generation → human_review → END
- 推送流程：START → wecom_push → END（人工确认后调用）

节点本身复用现有 analyzer / llm_reporter / wecom_sender，不重复实现业务逻辑。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .agent_state import AgentState
from .nodes.anomaly_analysis_node import anomaly_analysis_node
from .nodes.data_quality_node import data_quality_node
from .nodes.field_mapping_node import field_mapping_node
from .nodes.file_parse_node import file_parse_node
from .nodes.human_review_node import human_review_node
from .nodes.report_generation_node import report_generation_node
from .nodes.wecom_push_node import wecom_push_node


def _route_after_parse(state: AgentState) -> str:
    """条件路由：文件解析失败则直接短路到 END，跳过后续分析节点。"""
    return "abort" if state.get("errors") else "continue"


def build_analysis_graph():
    g = StateGraph(AgentState)
    g.add_node("file_parse", file_parse_node)
    g.add_node("field_mapping", field_mapping_node)
    g.add_node("data_quality", data_quality_node)
    g.add_node("anomaly_analysis", anomaly_analysis_node)
    g.add_node("report_generation", report_generation_node)
    g.add_node("human_review", human_review_node)
    g.add_edge(START, "file_parse")
    # 条件边：解析成功才继续，失败直接结束（真正的图分支，非线性顺序调用）
    g.add_conditional_edges("file_parse", _route_after_parse, {"continue": "field_mapping", "abort": END})
    g.add_edge("field_mapping", "data_quality")
    g.add_edge("data_quality", "anomaly_analysis")
    g.add_edge("anomaly_analysis", "report_generation")
    g.add_edge("report_generation", "human_review")
    g.add_edge("human_review", END)
    return g.compile()


def build_wecom_graph():
    g = StateGraph(AgentState)
    g.add_node("wecom_push", wecom_push_node)
    g.add_edge(START, "wecom_push")
    g.add_edge("wecom_push", END)
    return g.compile()


# 编译一次复用（无状态，线程安全足够 Demo 用）
_ANALYSIS_GRAPH = build_analysis_graph()
_WECOM_GRAPH = build_wecom_graph()


def run_analysis_workflow(
    file_path: str,
    file_name: str = "",
    *,
    use_llm: bool = True,
    force_mock: bool = False,
    send_wecom: bool = True,
) -> dict[str, Any]:
    """跑分析流程，返回最终 AgentState（dict）。"""
    init: AgentState = {
        "file_path": file_path,
        "file_name": file_name,
        "use_llm": use_llm,
        "force_mock": force_mock,
        "send_wecom": send_wecom,
        "steps": [],
        "errors": [],
    }
    return _ANALYSIS_GRAPH.invoke(init)


def run_wecom_push_workflow(report_markdown: str, *, send_wecom: bool = True) -> dict[str, Any]:
    """人工确认后跑推送流程，返回最终 AgentState（dict）。"""
    init: AgentState = {
        "report_markdown": report_markdown,
        "human_approved": True,    # 走到这里即代表人工已确认
        "send_wecom": send_wecom,
        "steps": [],
        "errors": [],
    }
    return _WECOM_GRAPH.invoke(init)


def graph_summary() -> dict[str, Any]:
    """导出分析图的节点 / 边 / mermaid——用于「确认这是真 LangGraph 编排」。"""
    g = _ANALYSIS_GRAPH.get_graph()
    return {
        "engine": type(_ANALYSIS_GRAPH).__module__ + "." + type(_ANALYSIS_GRAPH).__name__,
        "nodes": [n for n in g.nodes],
        "edges": [{"from": e.source, "to": e.target, "conditional": e.conditional} for e in g.edges],
        "mermaid": g.draw_mermaid(),
    }


if __name__ == "__main__":  # python -m app.agent_workflow → 打印图结构
    import json

    info = graph_summary()
    print("引擎：", info["engine"])
    print("节点：", info["nodes"])
    print("\nmermaid：\n" + info["mermaid"])
