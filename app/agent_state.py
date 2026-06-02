"""LangGraph 数字员工工作流的统一状态。

每个节点接收 AgentState、返回部分更新（dict）。
steps / errors 用 operator.add 作为 reducer——节点只需返回 {"steps": [一条]}，
LangGraph 会自动累加成完整的执行轨迹。
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    # 输入
    file_path: str
    file_name: str
    use_llm: bool
    force_mock: bool
    send_wecom: bool

    # FileParseNode
    raw_columns: list[str]
    total_rows: int
    preview_rows: list[dict[str, Any]]
    dataframe_records: list[dict[str, Any]]

    # FieldMappingNode
    mapped_columns: dict[str, str]          # canonical -> 原始列名
    recognized_fields: list[str]
    unrecognized_fields: list[str]

    # DataQualityNode
    data_quality: dict[str, Any]

    # AnomalyAnalysisNode
    analysis_result: dict[str, Any]

    # ReportGenerationNode
    report_markdown: str
    report_mode: str                        # mock / llm / rule / error
    llm_mode: str

    # HumanReviewNode
    need_human_review: bool
    human_approved: bool
    review_action: str                      # approve / reject / edit / revise / skip
    review_feedback: str                    # revise 时人工给的修改意见，喂回报告生成

    # WecomPushNode
    wecom_result: dict[str, Any]

    # 贯穿全程（累加）
    steps: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
