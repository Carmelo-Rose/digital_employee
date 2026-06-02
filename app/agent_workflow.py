"""LangGraph 数字员工工作流编排（HITL 单图版）。

单图结构：
  START → file_parse →(条件边:abort/continue)→ field_mapping
        → data_quality → anomaly_analysis → report_generation
        → human_review  ← interrupt() 在此真正阻断
        →(条件边:approve/reject)→ wecom_push → END
                               → END

关键升级：
- 合并原来两段图为一张图，消除"两次 invoke"的割裂感
- human_review_node 内调用 interrupt()，图在 checkpointer 层序列化冻结
- MemorySaver 作为 checkpointer，按 thread_id 隔离每次分析任务的状态
- 外部通过 Command(resume="approve"|"reject") 恢复图执行
- 条件边 _route_after_review 读取 state.human_approved 做最终路由
"""
from __future__ import annotations

import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .agent_state import AgentState
from .nodes.anomaly_analysis_node import anomaly_analysis_node
from .nodes.data_quality_node import data_quality_node
from .nodes.field_mapping_node import field_mapping_node
from .nodes.file_parse_node import file_parse_node
from .nodes.human_review_node import human_review_node
from .nodes.report_generation_node import report_generation_node
from .nodes.wecom_push_node import wecom_push_node

# ── checkpointer（进程内持久化，重启后清零；生产可换 SqliteSaver / RedisSaver）──
_CHECKPOINTER = MemorySaver()


# ── 条件路由函数 ──────────────────────────────────────────────────────────────

def _route_after_parse(state: AgentState) -> str:
    """文件解析失败则短路到 END，跳过后续所有节点。"""
    return "abort" if state.get("errors") else "continue"


def _route_after_review(state: AgentState) -> str:
    """人工审核后路由：
      revise         → 回 report_generation 重写（再次 interrupt 等待审核）
      approve / edit → wecom_push（需 send_wecom）
      reject / 其他  → END
    """
    action = state.get("review_action")
    if action == "revise":
        return "revise"
    if state.get("human_approved") and state.get("send_wecom"):
        return "approve"
    return "reject"


# ── 单图构建 ──────────────────────────────────────────────────────────────────

def build_unified_graph():
    """构建并编译含 interrupt + checkpointer 的单图。"""
    g = StateGraph(AgentState)

    # 节点注册
    g.add_node("file_parse", file_parse_node)
    g.add_node("field_mapping", field_mapping_node)
    g.add_node("data_quality", data_quality_node)
    g.add_node("anomaly_analysis", anomaly_analysis_node)
    g.add_node("report_generation", report_generation_node)
    g.add_node("human_review", human_review_node)
    g.add_node("wecom_push", wecom_push_node)

    # 边：START → 解析 →(条件)→ 分析链
    g.add_edge(START, "file_parse")
    g.add_conditional_edges(
        "file_parse",
        _route_after_parse,
        {"continue": "field_mapping", "abort": END},
    )
    g.add_edge("field_mapping", "data_quality")
    g.add_edge("data_quality", "anomaly_analysis")
    g.add_edge("anomaly_analysis", "report_generation")
    g.add_edge("report_generation", "human_review")

    # 边：human_review →(条件)→ wecom_push | END
    # interrupt() 发生在 human_review 节点内部，图在此阻断；
    # 恢复后 _route_after_review 读取已更新的 human_approved 做路由。
    g.add_conditional_edges(
        "human_review",
        _route_after_review,
        {"approve": "wecom_push", "revise": "report_generation", "reject": END},
    )
    g.add_edge("wecom_push", END)

    # 注入 checkpointer + 声明 interrupt 节点（LangGraph 要求显式声明）
    return g.compile(
        checkpointer=_CHECKPOINTER,
        interrupt_before=[],   # interrupt 由节点内 interrupt() 触发，无需 interrupt_before
    )


# 编译一次，全局复用（checkpointer 按 thread_id 隔离状态）
_GRAPH = build_unified_graph()


# ── 公共接口 ──────────────────────────────────────────────────────────────────

def start_workflow(
    file_path: str,
    file_name: str = "",
    *,
    use_llm: bool = True,
    force_mock: bool = False,
    send_wecom: bool = True,
    thread_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """启动分析工作流，图在 human_review interrupt 处阻断。

    返回 (thread_id, partial_state)：
    - thread_id：外部用于后续 resume_workflow 调用
    - partial_state：interrupt 前的图状态快照（含 report_markdown、steps 等）
    """
    tid = thread_id or uuid.uuid4().hex
    config = {"configurable": {"thread_id": tid}}

    init: AgentState = {
        "file_path": file_path,
        "file_name": file_name,
        "use_llm": use_llm,
        "force_mock": force_mock,
        "send_wecom": send_wecom,
        "steps": [],
        "errors": [],
    }

    # stream 事件直到图阻塞（interrupt）或结束
    # invoke 在 interrupt 时抛出 GraphInterrupt，改用 stream 逐事件消费更健壮
    final_state: dict[str, Any] = {}
    interrupted = False

    for event in _GRAPH.stream(init, config=config, stream_mode="values"):
        final_state = event  # 每个 event 是最新完整 state

    # 检查图是否停在 interrupt 点（而不是真正 END）
    snap = _GRAPH.get_state(config)
    if snap.next:  # snap.next 非空 → 图在 interrupt 处等待
        interrupted = True

    final_state["_thread_id"] = tid
    final_state["_interrupted"] = interrupted
    return tid, final_state


def resume_workflow(
    thread_id: str,
    decision: str,  # "approve" | "reject" | "edit" | "revise"
    *,
    edited_markdown: str | None = None,
    feedback: str | None = None,
) -> dict[str, Any]:
    """恢复被 interrupt 阻断的图。

    decision/payload 会作为 interrupt() 的返回值传回 human_review_node：
      - approve/reject → 路由到 wecom_push / END
      - edit           → edited_markdown 覆盖日报后推送
      - revise         → feedback 写入 state，路由回 report_generation 重写，
                         图会再次在 human_review 处 interrupt（_interrupted=True）
    """
    config = {"configurable": {"thread_id": thread_id}}

    resume_value: dict[str, Any] = {"action": decision}
    if edited_markdown is not None:
        resume_value["edited_markdown"] = edited_markdown
    if feedback is not None:
        resume_value["feedback"] = feedback

    final_state: dict[str, Any] = {}
    for event in _GRAPH.stream(
        Command(resume=resume_value),
        config=config,
        stream_mode="values",
    ):
        final_state = event

    # revise 会让图重新跑 report_generation → human_review 并再次 interrupt
    snap = _GRAPH.get_state(config)
    final_state["_thread_id"] = thread_id
    final_state["_interrupted"] = bool(snap.next)
    return final_state


def get_workflow_state(thread_id: str) -> dict[str, Any]:
    """查询指定 thread 的图状态（含 next 节点、values、interrupt 信息）。"""
    config = {"configurable": {"thread_id": thread_id}}
    snap = _GRAPH.get_state(config)
    if snap is None:
        return {"error": f"thread_id={thread_id!r} 不存在"}
    return {
        "thread_id": thread_id,
        "next": list(snap.next),
        "is_interrupted": bool(snap.next),
        "values": dict(snap.values),
        "metadata": snap.metadata,
    }


def graph_summary() -> dict[str, Any]:
    """导出单图的节点 / 边 / mermaid，用于 /workflow-graph API。"""
    g = _GRAPH.get_graph()
    return {
        "engine": type(_GRAPH).__module__ + "." + type(_GRAPH).__name__,
        "mode": "unified_hitl",
        "nodes": list(g.nodes),
        "edges": [
            {"from": e.source, "to": e.target, "conditional": e.conditional}
            for e in g.edges
        ],
        "mermaid": g.draw_mermaid(),
    }


# ── 向后兼容（旧路由仍可调用，内部走新图）────────────────────────────────────

def run_analysis_workflow(
    file_path: str,
    file_name: str = "",
    *,
    use_llm: bool = True,
    force_mock: bool = False,
    send_wecom: bool = True,
) -> dict[str, Any]:
    """兼容旧调用：启动图并在 interrupt 处返回 partial state。"""
    _, state = start_workflow(
        file_path, file_name,
        use_llm=use_llm, force_mock=force_mock, send_wecom=send_wecom,
    )
    return state


def run_wecom_push_workflow(
    report_markdown: str,
    *,
    send_wecom: bool = True,
    analysis_result: dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """兼容旧调用：若有 thread_id 则 resume，否则新建线程直接 approve。"""
    if thread_id:
        return resume_workflow(thread_id, "approve" if send_wecom else "reject")

    # 没有 thread_id：无法真正 resume，退化为单独调用 wecom_push_node
    from .nodes.wecom_push_node import wecom_push_node as _push
    fake_state: AgentState = {
        "report_markdown": report_markdown,
        "human_approved": True,
        "send_wecom": send_wecom,
        "analysis_result": analysis_result or {},
        "steps": [],
        "errors": [],
    }
    partial = _push(fake_state)
    return {**fake_state, **partial}


if __name__ == "__main__":
    import json
    info = graph_summary()
    print("引擎：", info["engine"])
    print("模式：", info["mode"])
    print("节点：", info["nodes"])
    print("\nmermaid：\n" + info["mermaid"])
