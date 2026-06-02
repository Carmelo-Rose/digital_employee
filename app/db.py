"""SQLite 持久化层（SQLAlchemy Core，无 ORM 依赖）。

表结构：
  analysis_reports —— 每次分析的快照，存核心指标 + 完整 JSON
  切换 MySQL/PostgreSQL：只需改 DATABASE_URL，其余不变。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# DB 文件放在项目根 data/ 目录，环境变量可覆盖
_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = f"sqlite:///{_ROOT / 'data' / 'reports.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_DB)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class AnalysisReport(Base):
    """每次分析结果的持久化快照。"""

    __tablename__ = "analysis_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(255), nullable=False)
    file_id = Column(String(64), nullable=False)
    report_date = Column(String(10), nullable=False)   # YYYY-MM-DD，来自分析结果
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 核心指标（冗余存储，方便列表页快速展示和环比计算，无需反序列化 JSON）
    total_orders = Column(Integer, default=0)
    anomaly_total = Column(Integer, default=0)
    anomaly_orders = Column(Integer, default=0)

    # 各异常类别计数，JSON 格式：{"paid_not_shipped": 3, ...}
    summary_json = Column(Text, nullable=False, default="{}")

    # 完整分析结果（analysis_result dict）和报告 Markdown
    analysis_json = Column(Text, nullable=False, default="{}")
    report_markdown = Column(Text, nullable=False, default="")
    report_mode = Column(String(20), default="rule")


def init_db() -> None:
    """建表（幂等）。"""
    Base.metadata.create_all(engine)


def get_db() -> Session:
    """依赖注入用；FastAPI 路由中 Depends(get_db) 或手动 with get_db() as db。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_report(
    *,
    file_name: str,
    file_id: str,
    analysis: dict[str, Any],
    report_markdown: str,
    report_mode: str,
) -> int:
    """持久化一条分析结果，返回自增 id。"""
    summary = analysis.get("summary", {})
    row = AnalysisReport(
        file_name=file_name,
        file_id=file_id,
        report_date=analysis.get("date", datetime.utcnow().strftime("%Y-%m-%d")),
        total_orders=int(analysis.get("total_orders", 0)),
        anomaly_total=int(analysis.get("anomaly_total", 0)),
        anomaly_orders=int(analysis.get("anomaly_orders", 0)),
        summary_json=json.dumps(summary, ensure_ascii=False),
        analysis_json=json.dumps(analysis, ensure_ascii=False, default=str),
        report_markdown=report_markdown,
        report_mode=report_mode,
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def update_report_markdown(report_id: int, report_markdown: str, report_mode: str | None = None) -> bool:
    """人工 edit/revise 后，把最终日报同步回库，保持历史与实际推送一致。"""
    with SessionLocal() as db:
        row = db.get(AnalysisReport, report_id)
        if not row:
            return False
        row.report_markdown = report_markdown
        if report_mode:
            row.report_mode = report_mode
        db.commit()
        return True


def list_reports(limit: int = 50) -> list[dict[str, Any]]:
    """返回最近 limit 条报告摘要（不含完整 JSON，节省传输）。"""
    with SessionLocal() as db:
        rows = (
            db.query(AnalysisReport)
            .order_by(AnalysisReport.id.desc())
            .limit(limit)
            .all()
        )
        return [_to_summary(r) for r in rows]


def get_report(report_id: int) -> dict[str, Any] | None:
    """返回单条完整报告（含 analysis_json）。"""
    with SessionLocal() as db:
        row = db.get(AnalysisReport, report_id)
        if not row:
            return None
        return _to_full(row)


def get_prev_report(report_id: int) -> dict[str, Any] | None:
    """返回 report_id 的上一条报告（id 最大且 < report_id）。"""
    with SessionLocal() as db:
        row = (
            db.query(AnalysisReport)
            .filter(AnalysisReport.id < report_id)
            .order_by(AnalysisReport.id.desc())
            .first()
        )
        return _to_full(row) if row else None


# ── 私有转换 ──────────────────────────────────────────────────────────────────

def _to_summary(r: AnalysisReport) -> dict[str, Any]:
    return {
        "id": r.id,
        "file_name": r.file_name,
        "file_id": r.file_id,
        "report_date": r.report_date,
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        "total_orders": r.total_orders,
        "anomaly_total": r.anomaly_total,
        "anomaly_orders": r.anomaly_orders,
        "summary": json.loads(r.summary_json or "{}"),
        "report_mode": r.report_mode,
    }


def _to_full(r: AnalysisReport) -> dict[str, Any]:
    d = _to_summary(r)
    d["analysis_result"] = json.loads(r.analysis_json or "{}")
    d["report_markdown"] = r.report_markdown
    return d
