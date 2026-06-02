"""第五/5.5 阶段：LangGraph 工作流测试（含真实编排实证 + 业务判断文案）。"""
from __future__ import annotations

from app.agent_workflow import (
    graph_summary,
    resume_workflow,
    run_analysis_workflow,
    run_wecom_push_workflow,
    start_workflow,
)
from app.config import SAMPLE_CSV


def test_real_langgraph_engine_and_nodes():
    info = graph_summary()
    # 确认是真正编译出来的 LangGraph，而非顺序函数调用
    assert "CompiledStateGraph" in info["engine"]
    for node in ("file_parse", "field_mapping", "data_quality",
                 "anomaly_analysis", "report_generation", "human_review"):
        assert node in info["nodes"]
    # 确认存在条件边（真正的图分支）
    assert any(e["conditional"] for e in info["edges"]), "应有条件边（解析失败短路）"
    assert "mermaid" in info and "file_parse" in info["mermaid"]


def test_analysis_workflow_interrupts_before_review():
    # 单图 interrupt 设计：跑到 human_review 处阻断，steps 止于「AI 日报生成」，
    # human_review 的步骤要等 resume 后才产生。
    st = run_analysis_workflow(str(SAMPLE_CSV), "sample_orders.csv", use_llm=True, force_mock=True)
    names = [s["name"] for s in st["steps"]]
    assert names == ["读取订单数据", "字段映射", "数据质量检查", "异常分析", "AI 日报生成"]
    assert st["_interrupted"] is True
    assert st["report_markdown"] and st["report_mode"] == "mock"


def test_hitl_approve_then_push():
    tid, st = start_workflow(str(SAMPLE_CSV), "s.csv", use_llm=True, force_mock=True)
    assert st["_interrupted"] is True
    out = resume_workflow(tid, "approve")
    assert out["_interrupted"] is False
    assert out["human_approved"] is True
    assert out["review_action"] == "approve"
    assert out["wecom_result"]["status"] in {"missing_webhook", "success"}


def test_hitl_edit_pushes_edited_version():
    tid, _ = start_workflow(str(SAMPLE_CSV), "s.csv", use_llm=True, force_mock=True)
    edited = "# 人工改写版日报\n\n## 今日订单概况\n手动核对后的内容。"
    out = resume_workflow(tid, "edit", edited_markdown=edited)
    assert out["_interrupted"] is False
    assert out["review_action"] == "edit"
    assert out["report_markdown"] == edited            # 推送的是编辑后的版本
    assert out["wecom_result"]["status"] in {"missing_webhook", "success"}


def test_hitl_revise_loops_back_then_approve():
    tid, _ = start_workflow(str(SAMPLE_CSV), "s.csv", use_llm=True, force_mock=True)
    revised = resume_workflow(tid, "revise", feedback="物流部分再展开写细一点")
    # revise 回流 report_generation 后再次在 human_review 处 interrupt
    assert revised["_interrupted"] is True
    assert "物流部分再展开写细一点" in revised["report_markdown"]   # mock 回显已采纳意见
    # 复审后批准，闭环完成
    final = resume_workflow(tid, "approve")
    assert final["_interrupted"] is False
    assert final["human_approved"] is True


def test_parse_failure_short_circuits():
    st = run_analysis_workflow("data/__not_exist__.csv", "x.csv")
    assert st.get("errors")
    # 条件边生效：解析失败后直接结束，不再产生后续节点步骤
    assert [s["name"] for s in st["steps"]] == ["读取订单数据"]
    assert st["steps"][0]["status"] == "error"
    assert not st.get("report_markdown")
    assert not st.get("need_human_review")


def test_wecom_workflow_no_webhook():
    st = run_wecom_push_workflow("# 测试日报\n内容", send_wecom=True)
    assert st["wecom_result"]["status"] in {"missing_webhook", "success"}


def test_report_has_business_judgment():
    st = run_analysis_workflow(str(SAMPLE_CSV), "s.csv", use_llm=True, force_mock=True)
    md = st["report_markdown"]
    assert "高优先（今天必须处理）" in md
    assert "中优先" in md
    assert "主战场" in md
