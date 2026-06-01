"""HTTP 路由：上传 / 分析 / 推送。"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..agent_workflow import graph_summary, run_analysis_workflow, run_wecom_push_workflow
from ..config import UPLOAD_DIR
from ..loader import read_orders_table as _read_table
from ..push import push_report
from ..schema import resolve_columns

router = APIRouter(prefix="/api")

ALLOWED_EXT = {".csv", ".xlsx", ".xls"}


@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"仅支持 {', '.join(sorted(ALLOWED_EXT))}，收到 {ext or '未知'}")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / file_id
    dest.write_bytes(await file.read())

    try:
        df = _read_table(dest)
    except Exception as e:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"文件解析失败：{e}") from e

    resolved = resolve_columns(df)
    preview = df.head(5).fillna("").astype(str).to_dict(orient="records")
    return {
        "file_id": file_id,
        "filename": file.filename,
        "rows": int(len(df)),
        "recognized_columns": resolved,        # canonical -> 原始列名
        "unrecognized_columns": [str(c) for c in df.columns if c not in resolved.values()],
        "preview": preview,
    }


class AnalyzeReq(BaseModel):
    file_id: str
    use_llm: bool = False      # True → 生成 7 板块 AI 日报；False → 规则版
    force_mock: bool = False   # AI 日报强制走 mock，不调真实模型


@router.get("/workflow-graph")
async def workflow_graph() -> dict:
    """返回 LangGraph 编排结构（节点/边/mermaid），用于确认真实编排。"""
    return graph_summary()


@router.post("/analyze")
async def analyze(req: AnalyzeReq) -> dict:
    """跑 LangGraph 分析工作流（file_parse → … → human_review），返回真实节点 steps。"""
    path = UPLOAD_DIR / req.file_id
    if not path.exists():
        raise HTTPException(404, "文件不存在，请重新上传")

    state = run_analysis_workflow(
        str(path), req.file_id, use_llm=req.use_llm, force_mock=req.force_mock,
    )
    analysis = state.get("analysis_result") or {}
    return {
        "steps": state.get("steps", []),
        "preview_rows": state.get("preview_rows", []),
        "total_rows": state.get("total_rows", 0),
        "recognized_fields": state.get("recognized_fields", []),
        "unrecognized_fields": state.get("unrecognized_fields", []),
        "data_quality": state.get("data_quality", {}),
        "analysis_result": analysis,
        "summary": analysis,                       # 兼容前端 renderSummary
        "report_markdown": state.get("report_markdown", ""),
        "report_mode": state.get("report_mode") or state.get("llm_mode", ""),
        "need_human_review": state.get("need_human_review", False),
        "errors": state.get("errors", []),
    }


class PushReq(BaseModel):
    report_markdown: str
    channel: str = "wecom"


@router.post("/push")
async def push(req: PushReq) -> dict:
    """通用推送（支持 channel=wecom/feishu），保留给 API/飞书用。"""
    if not req.report_markdown.strip():
        raise HTTPException(400, "日报内容为空，请先分析")
    return push_report(req.report_markdown, channel=req.channel)


class WecomReq(BaseModel):
    report_markdown: str


@router.post("/send-wecom")
async def send_wecom(req: WecomReq) -> dict:
    """人工确认按钮：设 human_approved=true，跑 LangGraph 推送工作流。

    未配置 WECOM_WEBHOOK_URL 时 status=missing_webhook（模拟成功），不报错不崩溃。
    """
    if not req.report_markdown.strip():
        raise HTTPException(400, "日报内容为空，请先分析")
    state = run_wecom_push_workflow(req.report_markdown, send_wecom=True)
    wr = state.get("wecom_result", {})
    status = wr.get("status")
    # 兼容前端：保留 ok / mock 字段
    return {
        **wr,
        "ok": status in {"success", "missing_webhook"},
        "mock": status == "missing_webhook",
        "steps": state.get("steps", []),
    }
