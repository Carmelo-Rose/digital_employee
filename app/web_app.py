"""第四阶段 Web 入口别名。

为兼容文档里的启动命令 `uvicorn app.web_app:app --reload`，这里直接复用
app/main.py 里已组装好的 FastAPI 实例，不重复定义路由 / 静态托管。

两种启动命令等价：
    uvicorn app.web_app:app --reload
    uvicorn app.main:app --reload
"""
from __future__ import annotations

from .main import app  # noqa: F401  —— 供 uvicorn app.web_app:app 使用
