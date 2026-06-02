"""HTTP 路由：上传 / 分析 / HITL恢复 / 历史报告 / 环比。

HITL 工作流（单图版）：
  POST /api/analyze        → 启动图，图在 human_review interrupt 处阻断
                             返回 thread_id + partial_state（含 report_markdown）
  GET  /api/graph-state/{thread_id} → 查询图当前状态（是否仍在等待中断）
  POST /api/resume         → 传入 thread_id + decision("approve"|"reject")
                             Command(resume=decision) 恢复图执行
                             approved → wecom_push → END
                             rejected → END（跳过推送）

旧 /api/send-wecom 仍保留，兼容前端直接推送场景。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..agent_workflow import (
    get_workflow_state,
    graph_summary,
    resume_workflow,
    run_wecom_push_workflow,
    start_workflow,
)
from ..config import UPLOAD_DIR
from ..db import (
    get_prev_report,
    get_report,
    list_reports,
    save_report,
    update_report_markdown,
)
from ..loader import read_orders_table as _read_table
from ..memory import (
    THRESHOLD_KEYS,
    get_field_overrides,
    get_thresholds,
    set_field_override,
    set_thresholds,
)
from ..domains import get_domain
from ..push import push_report
from ..scheduler import get_scheduler_status, trigger_now

router = APIRouter(prefix="/api")

ALLOWED_EXT = {".csv", ".xlsx", ".xls"}


# ── 上传 ──────────────────────────────────────────────────────────────────────

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

    # 上传阶段用默认域做列预览；分析阶段会由 domain_name 参数精确识别
    # 叠加用户记忆的字段映射纠正，让预览即体现「上次教过的列」
    domain = get_domain()
    overrides = get_field_overrides()
    aliases = domain.column_aliases
    col_lookup = {str(c).strip().lower(): str(c) for c in df.columns}
    resolved: dict[str, str] = {}
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            if alias.lower() in col_lookup:
                resolved[canonical] = col_lookup[alias.lower()]
                break
    if overrides:
        for raw_lower, canonical in overrides.items():
            if canonical and raw_lower in col_lookup:
                resolved[canonical] = col_lookup[raw_lower]

    preview = df.head(5).fillna("").astype(str).to_dict(orient="records")
    return {
        "file_id": file_id,
        "filename": file.filename,
        "rows": int(len(df)),
        "recognized_columns": resolved,
        "unrecognized_columns": [str(c) for c in df.columns if c not in resolved.values()],
        "preview": preview,
    }


# ── 图结构查询 ────────────────────────────────────────────────────────────────

@router.get("/workflow-graph")
async def workflow_graph() -> dict:
    return graph_summary()


# ── HITL 分析流程（启动 → interrupt → resume）────────────────────────────────

class AnalyzeReq(BaseModel):
    file_id: str
    file_name: str = ""
    use_llm: bool = False
    force_mock: bool = False
    send_wecom: bool = True
    domain_name: str = "ecommerce"  # 业务域标识，扩展新业务时由前端/调用方传入


@router.post("/analyze")
async def analyze(req: AnalyzeReq) -> dict:
    """启动 LangGraph 单图工作流。

    图执行到 human_review 节点时 interrupt() 阻断，本接口立即返回：
    - thread_id：后续 /resume 调用凭证
    - interrupted=True：前端据此知道需要等待人工确认
    - report_markdown / steps 等：interrupt 前已产出的数据
    """
    path = UPLOAD_DIR / req.file_id
    if not path.exists():
        raise HTTPException(404, "文件不存在，请重新上传")

    thread_id, state = start_workflow(
        str(path),
        req.file_name or req.file_id,
        use_llm=req.use_llm,
        force_mock=req.force_mock,
        send_wecom=req.send_wecom,
    )

    analysis = state.get("analysis_result") or {}
    report_markdown = state.get("report_markdown", "")
    report_mode = state.get("report_mode") or state.get("llm_mode", "rule")

    # 持久化分析结果（此时尚未推送）
    file_name = req.file_name or req.file_id
    report_id = save_report(
        file_name=file_name,
        file_id=req.file_id,
        analysis=analysis,
        report_markdown=report_markdown,
        report_mode=report_mode,
    )

    return {
        # HITL 凭证
        "thread_id": thread_id,
        "interrupted": state.get("_interrupted", False),
        "report_id": report_id,
        # 分析数据
        "steps": state.get("steps", []),
        "preview_rows": state.get("preview_rows", []),
        "total_rows": state.get("total_rows", 0),
        "recognized_fields": state.get("recognized_fields", []),
        "unrecognized_fields": state.get("unrecognized_fields", []),
        "data_quality": state.get("data_quality", {}),
        "analysis_result": analysis,
        "summary": analysis,
        "report_markdown": report_markdown,
        "report_mode": report_mode,
        "need_human_review": state.get("need_human_review", False),
        "errors": state.get("errors", []),
    }


class ResumeReq(BaseModel):
    thread_id: str
    decision: str = "approve"          # approve | reject | edit | revise
    edited_markdown: str | None = None  # edit 时人工改写后的日报
    feedback: str | None = None         # revise 时给 AI 的修改意见
    report_id: int | None = None        # 有值时把最终日报同步回库


_RESUME_ACTIONS = {"approve", "reject", "edit", "revise"}


@router.post("/resume")
async def resume(req: ResumeReq) -> dict:
    """恢复被 interrupt 阻断的图，支持 4 种人工动作。

    approve → wecom_push → END
    reject  → END（跳过推送）
    edit    → 用 edited_markdown 覆盖日报后推送
    revise  → 写入 feedback 回 report_generation 重写，图再次 interrupt 等待复审
    """
    if req.decision not in _RESUME_ACTIONS:
        raise HTTPException(400, f"decision 须为 {sorted(_RESUME_ACTIONS)} 之一，收到 {req.decision!r}")
    if req.decision == "edit" and not (req.edited_markdown or "").strip():
        raise HTTPException(400, "edit 操作必须提供 edited_markdown")
    if req.decision == "revise" and not (req.feedback or "").strip():
        raise HTTPException(400, "revise 操作必须提供 feedback")

    # 先确认 thread 仍处于 interrupted 状态
    snap = get_workflow_state(req.thread_id)
    if "error" in snap:
        raise HTTPException(404, snap["error"])
    if not snap.get("is_interrupted"):
        raise HTTPException(409, f"thread_id={req.thread_id!r} 的图已结束或不存在等待中断")

    state = resume_workflow(
        req.thread_id,
        req.decision,
        edited_markdown=req.edited_markdown,
        feedback=req.feedback,
    )

    report_markdown = state.get("report_markdown", "")
    report_mode = state.get("report_mode") or state.get("llm_mode", "rule")
    interrupted = state.get("_interrupted", False)

    # edit/revise 改了日报内容 → 同步回库，保持历史与推送一致
    if req.report_id and req.decision in {"edit", "revise"} and report_markdown:
        update_report_markdown(req.report_id, report_markdown, report_mode)

    wr = state.get("wecom_result") or {}
    return {
        "thread_id": req.thread_id,
        "decision": req.decision,
        # revise 后图再次中断，前端据此回到「等待复审」状态并展示重写后的日报
        "interrupted": interrupted,
        "report_markdown": report_markdown,
        "report_mode": report_mode,
        "human_approved": state.get("human_approved", False),
        "wecom_result": wr,
        "wecom_ok": wr.get("status") in {"success", "missing_webhook"},
        "wecom_mock": wr.get("status") == "missing_webhook",
        "steps": state.get("steps", []),
        "errors": state.get("errors", []),
    }


@router.get("/graph-state/{thread_id}")
async def graph_state(thread_id: str) -> dict:
    """查询指定 thread 的图状态，可用于轮询 interrupt 是否已恢复。"""
    snap = get_workflow_state(thread_id)
    if "error" in snap:
        raise HTTPException(404, snap["error"])
    return snap


# ── 历史报告 ──────────────────────────────────────────────────────────────────

@router.get("/reports")
async def reports_list(limit: int = 50) -> dict:
    return {"reports": list_reports(limit=limit)}


@router.get("/reports/{report_id}")
async def report_detail(report_id: int) -> dict:
    row = get_report(report_id)
    if not row:
        raise HTTPException(404, f"报告 {report_id} 不存在")
    return row


# ── 环比 ──────────────────────────────────────────────────────────────────────

@router.get("/reports/{report_id}/compare")
async def compare_report(report_id: int, prev_id: int | None = None) -> dict:
    current = get_report(report_id)
    if not current:
        raise HTTPException(404, f"报告 {report_id} 不存在")

    prev = get_report(prev_id) if prev_id else get_prev_report(report_id)
    if not prev:
        return {
            "report_id": report_id,
            "prev_id": None,
            "has_prev": False,
            "message": "暂无历史数据可对比",
        }

    return {
        "report_id": report_id,
        "prev_id": prev["id"],
        "has_prev": True,
        "current_date": current["report_date"],
        "prev_date": prev["report_date"],
        "metrics": _build_compare(current, prev),
    }


def _build_compare(cur: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
    def _delta(c: int | float, p: int | float) -> dict:
        diff = c - p
        pct = round(diff / p * 100, 1) if p else None
        return {"current": c, "prev": p, "delta": diff, "pct": pct}

    cur_summary = cur.get("summary", {})
    prev_summary = prev.get("summary", {})
    all_keys = set(cur_summary) | set(prev_summary)

    categories: dict[str, Any] = {}
    for k in all_keys:
        categories[k] = _delta(cur_summary.get(k, 0), prev_summary.get(k, 0))

    return {
        "total_orders": _delta(cur["total_orders"], prev["total_orders"]),
        "anomaly_total": _delta(cur["anomaly_total"], prev["anomaly_total"]),
        "anomaly_orders": _delta(cur["anomaly_orders"], prev["anomaly_orders"]),
        "categories": categories,
    }


# ── 自主触发（定时调度，无需人工上传）────────────────────────────────────────

@router.get("/scheduler")
async def scheduler_status() -> dict:
    """查看自主触发状态：开关 / 是否运行 / 下次运行时间 / 最近一次结果 / 待确认列表。"""
    return get_scheduler_status()


@router.post("/scheduler/run-now")
async def scheduler_run_now() -> dict:
    """手动立即触发一次完整工作流（不必等 cron 到点）。

    走与定时任务完全相同的链路：取数据 → 跑图 → 落库 →
    （auto-approve 直接推送 / require_review 推待确认通知）。
    """
    return trigger_now()


# ── 推送（兼容旧接口）─────────────────────────────────────────────────────────

class PushReq(BaseModel):
    report_markdown: str
    channel: str = "wecom"
    analysis_result: dict | None = None


@router.post("/push")
async def push(req: PushReq) -> dict:
    if not req.report_markdown.strip():
        raise HTTPException(400, "日报内容为空，请先分析")
    return push_report(req.report_markdown, channel=req.channel, analysis=req.analysis_result)


class WecomReq(BaseModel):
    report_markdown: str
    analysis_result: dict | None = None
    thread_id: str | None = None   # 有值时走 resume，否则退化直推


@router.post("/send-wecom")
async def send_wecom(req: WecomReq) -> dict:
    """兼容旧前端：直接推送（不经过 HITL 流程）。"""
    if not req.report_markdown.strip():
        raise HTTPException(400, "日报内容为空，请先分析")
    state = run_wecom_push_workflow(
        req.report_markdown,
        send_wecom=True,
        analysis_result=req.analysis_result,
        thread_id=req.thread_id,
    )
    wr = state.get("wecom_result", {})
    status = wr.get("status")
    return {
        **wr,
        "ok": status in {"success", "missing_webhook"},
        "mock": status == "missing_webhook",
        "steps": state.get("steps", []),
    }


# ── 业务规则记忆（字段映射纠正 + 阈值持久化）────────────────────────────────────

# 阈值名 → 中文标签（前端展示用）
_THRESHOLD_LABELS = {
    "pay_no_ship_hours": "付款超 N 小时未发货算严重",
    "logistics_stale_days": "物流超 N 天无更新算异常",
    "refund_pending_days": "退款中超 N 天未完成算异常",
    "stock_low_threshold": "库存 ≤ N 算偏低",
}


@router.get("/memory")
async def get_memory() -> dict:
    """返回当前记忆：字段映射纠正 + 阈值，并附可选 canonical 字段清单供前端下拉。"""
    return {
        "field_overrides": get_field_overrides(),
        "thresholds": get_thresholds(),
        "available_fields": [
            {"canonical": k, "label": v} for k, v in get_domain().canonical_labels.items()
        ],
        "threshold_defs": [
            {"key": k, "label": _THRESHOLD_LABELS.get(k, k)} for k in THRESHOLD_KEYS
        ],
    }


class FieldOverrideReq(BaseModel):
    raw_column: str
    canonical: str | None = None   # 留空 → 删除该条记忆


@router.post("/memory/field-override")
async def post_field_override(req: FieldOverrideReq) -> dict:
    """记住一条字段映射纠正（下次上传同名列即自动识别）。"""
    try:
        overrides = set_field_override(req.raw_column, req.canonical)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "field_overrides": overrides}


class ThresholdsReq(BaseModel):
    thresholds: dict[str, Any]     # {阈值名: 正整数 | None(删除)}


@router.post("/memory/thresholds")
async def post_thresholds(req: ThresholdsReq) -> dict:
    """更新并持久化规则阈值（覆盖 Config 默认值）。"""
    try:
        saved = set_thresholds(req.thresholds)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "thresholds": saved}
