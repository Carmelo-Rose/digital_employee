"""APScheduler 自主触发层：让数字员工"自己上班"。

把"人工上传 → 点开始分析"这一步去掉，由定时器（cron / interval）自动触发
完整的 LangGraph 工作流：

    resolve_order_file()  取数据（当前=固定文件，可扩展为扫目录/接平台 API）
      → start_workflow()  跑图（解析→映射→质量→异常→生成报告，在 human_review 处 interrupt）
      → save_report()     落库（复用 db 层，历史/环比共用同一份数据）
      → 按 SCHEDULER_REQUIRE_REVIEW 二选一：
          False(默认)：resume(approve) 自动推送        —— 真正无人值守闭环
          True       ：推一条"待确认"通知 + 留 pending —— 保留人在回路(HITL)

数据源抽象：定时任务只依赖 resolve_order_file()。当前实现读固定路径
（settings.scheduler_input_file，留空回退 sample）。以后要监控 inbox 目录、
或调电商平台 OpenAPI，只改这一个函数，调度与工作流代码一行都不用动。

图状态用 agent_workflow 里的进程内 MemorySaver——pending thread 在进程存活期内
可被 /api/resume 恢复；进程重启清零。生产把 _CHECKPOINTER 换成 SqliteSaver/
PostgresSaver 即可让待确认任务跨重启恢复。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .agent_workflow import get_workflow_state, resume_workflow, start_workflow
from .config import DATA_DIR, settings
from .db import save_report
from .push import push_report

logger = logging.getLogger("digital_employee.scheduler")

_JOB_ID = "daily_analysis"

# 模块级状态：供 /api/scheduler 观测
_scheduler: BackgroundScheduler | None = None
_last_run: dict[str, Any] | None = None
_pending: list[dict[str, Any]] = []


# ── 数据源抽象（唯一需要随接入方式变化的地方）──────────────────────────────────

def resolve_order_file() -> Path | None:
    """返回本次定时任务要分析的订单文件，找不到返回 None。

    当前实现：固定路径（settings.scheduler_input_file，留空回退 sample）。
    ── 扩展位（以后只改这里）──
    · 监控目录：取 DATA_DIR/"inbox" 下最新的 .xlsx/.csv
    · 接平台 API：拉单 → 落临时文件 → 返回其路径
    """
    configured = settings.scheduler_input_file
    path = Path(configured) if configured else DATA_DIR / "sample_orders.xlsx"
    if not path.is_absolute():
        # 相对路径按项目根解析
        path = (DATA_DIR.parent / path).resolve()
    return path if path.exists() else None


# ── 核心任务 ──────────────────────────────────────────────────────────────────

def run_scheduled_analysis(*, manual: bool = False) -> dict[str, Any]:
    """定时任务主体：取数据 → 跑图 → 落库 → 推送 / 待确认。

    manual=True 表示来自 /api/scheduler/run-now 的手动触发（不等 cron）。
    结果摘要会记录到 _last_run，供 /api/scheduler 观测。
    """
    global _last_run
    trigger_kind = "manual" if manual else "scheduled"
    started = datetime.now()

    path = resolve_order_file()
    if path is None:
        _last_run = {
            "ok": False,
            "trigger": trigger_kind,
            "ran_at": started.strftime("%Y-%m-%d %H:%M:%S"),
            "error": "未找到可分析的订单文件（检查 SCHEDULER_INPUT_FILE 或 data/sample_orders.xlsx）",
        }
        logger.warning("自主触发失败：%s", _last_run["error"])
        return _last_run

    logger.info("自主触发[%s]开始分析：%s", trigger_kind, path.name)
    thread_id, state = start_workflow(
        str(path),
        path.name,
        use_llm=settings.scheduler_use_llm,
        send_wecom=settings.scheduler_send_wecom,
    )

    analysis = state.get("analysis_result") or {}
    report_markdown = state.get("report_markdown", "")
    report_mode = state.get("report_mode") or state.get("llm_mode", "rule")
    errors = state.get("errors") or []

    report_id = save_report(
        file_name=path.name,
        file_id=f"scheduler:{path.name}",
        analysis=analysis,
        report_markdown=report_markdown,
        report_mode=report_mode,
    )

    result: dict[str, Any] = {
        "ok": True,
        "trigger": trigger_kind,
        "ran_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "file": path.name,
        "report_id": report_id,
        "thread_id": thread_id,
        "report_mode": report_mode,
        "total_orders": analysis.get("total_orders", 0),
        "anomaly_orders": analysis.get("anomaly_orders", 0),
        "errors": errors,
    }

    # 上游解析失败：图已短路到 END，无报告可推
    if errors or not report_markdown:
        result["mode"] = "error"
        result["message"] = "分析未产出报告（上游错误或空数据），未推送"
        _last_run = result
        return result

    if settings.scheduler_require_review:
        # 保留 HITL：推"待确认"通知，留 pending thread 等人确认
        notice = _build_review_notice(path.name, analysis, report_id, thread_id)
        push_res = push_report(notice, channel="wecom")
        _pending.append({
            "thread_id": thread_id,
            "report_id": report_id,
            "file": path.name,
            "anomaly_orders": analysis.get("anomaly_orders", 0),
            "created_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        })
        result["mode"] = "await_review"
        result["message"] = "已生成日报并推送『待确认』通知，等待人工确认后发送正式日报"
        result["notice_pushed"] = push_res.get("ok", False)
    else:
        # 无人值守闭环：自动批准 → 图继续 wecom_push → END
        final = resume_workflow(thread_id, "approve")
        wr = final.get("wecom_result") or {}
        result["mode"] = "auto_pushed"
        result["message"] = "已自动批准并推送企业微信日报"
        result["wecom_status"] = wr.get("status")
        result["wecom_ok"] = wr.get("status") in {"success", "missing_webhook"}

    _last_run = result
    logger.info("自主触发[%s]完成：mode=%s report_id=%s", trigger_kind, result["mode"], report_id)
    return result


def _build_review_notice(file_name: str, analysis: dict[str, Any], report_id: int, thread_id: str) -> str:
    """require_review 模式下推给运营的"待确认"通知文案。"""
    total = analysis.get("total_orders", 0)
    anomaly = analysis.get("anomaly_orders", 0)
    return (
        f"# 🤖 数字员工 · 今日日报待确认\n\n"
        f"已自动分析 **{file_name}**：共 {total} 单，发现 {anomaly} 单异常。\n\n"
        f"报告已生成（report_id={report_id}），等待人工确认后推送正式日报。\n\n"
        f"> 确认推送：调用 POST /api/resume "
        f'{{"thread_id": "{thread_id}", "decision": "approve"}}，'
        f"或在系统历史页查看后确认。"
    )


# ── 调度器生命周期 ────────────────────────────────────────────────────────────

def _build_trigger() -> tuple[Any, str]:
    """按配置造 cron / interval trigger，返回 (trigger, 描述)。"""
    tz = settings.scheduler_timezone
    if settings.scheduler_cron:
        return CronTrigger.from_crontab(settings.scheduler_cron, timezone=tz), f"cron({settings.scheduler_cron})"
    if settings.scheduler_interval_minutes > 0:
        return (
            IntervalTrigger(minutes=settings.scheduler_interval_minutes, timezone=tz),
            f"interval({settings.scheduler_interval_minutes}m)",
        )
    return CronTrigger(hour=9, minute=0, timezone=tz), "cron(每天09:00 默认)"


def start_scheduler() -> dict[str, Any]:
    """随 FastAPI startup 调用；SCHEDULER_ENABLED=false 时跳过。"""
    global _scheduler
    if not settings.scheduler_enabled:
        logger.info("自主触发未开启（SCHEDULER_ENABLED=false），跳过调度器启动")
        return {"enabled": False, "running": False}
    if _scheduler and _scheduler.running:
        return get_scheduler_status()

    trigger, desc = _build_trigger()
    _scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)
    _scheduler.add_job(
        run_scheduled_analysis,
        trigger=trigger,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,   # 同一时刻只跑一个，避免重叠
        coalesce=True,     # 错过的触发合并为一次，不补跑堆积
    )
    _scheduler.start()
    logger.info("自主触发已启动：%s，require_review=%s", desc, settings.scheduler_require_review)
    return get_scheduler_status()


def shutdown_scheduler() -> None:
    """随 FastAPI shutdown 调用。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("自主触发调度器已停止")
    _scheduler = None


# ── 观测 / 手动触发 ───────────────────────────────────────────────────────────

def trigger_now() -> dict[str, Any]:
    """手动立即跑一次（不必等 cron 到点）。无论 enabled 与否都可调。"""
    return run_scheduled_analysis(manual=True)


def list_pending() -> list[dict[str, Any]]:
    """返回仍在等待确认的任务（实时过滤掉已被 resume 的）。"""
    alive = [item for item in _pending if get_workflow_state(item["thread_id"]).get("is_interrupted")]
    _pending[:] = alive   # 原地收敛，避免列表无限增长
    return alive


def get_scheduler_status() -> dict[str, Any]:
    """供 GET /api/scheduler：开关、是否运行、下次运行时间、最近一次结果、待确认列表。"""
    running = bool(_scheduler and _scheduler.running)
    job = _scheduler.get_job(_JOB_ID) if running else None
    next_run = (
        job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
        if (job and job.next_run_time) else None
    )
    return {
        "enabled": settings.scheduler_enabled,
        "running": running,
        "next_run": next_run,
        "require_review": settings.scheduler_require_review,
        "input_file": settings.scheduler_input_file or "data/sample_orders.xlsx（默认）",
        "use_llm": settings.scheduler_use_llm,
        "last_run": _last_run,
        "pending": list_pending(),
    }
