"""FastAPI 入口：挂载 API 路由 + 托管前端静态页。

启动： uvicorn app.main:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .config import STATIC_DIR
from .db import init_db
from .scheduler import shutdown_scheduler, start_scheduler

app = FastAPI(title="电商运营数字员工", version="0.1.0")
app.include_router(api_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # 自主触发：SCHEDULER_ENABLED=true 时随服务启动定时任务，否则跳过
    start_scheduler()


@app.on_event("shutdown")
def _shutdown() -> None:
    shutdown_scheduler()

# 前端静态资源（js/css）
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
