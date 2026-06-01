"""FastAPI 入口：挂载 API 路由 + 托管前端静态页。

启动： uvicorn app.main:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .config import STATIC_DIR

app = FastAPI(title="电商运营数字员工 Demo", version="0.1.0")
app.include_router(api_router)

# 前端静态资源（js/css）
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
