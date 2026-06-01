"""节点公用小工具：统一生成执行步骤。

step 结构供前端展示：
- status="done"    → ✅ 已完成
- status="waiting" → 🕓 等待（人工确认）
- status="error"   → ❌ 失败
"""
from __future__ import annotations

from typing import Any


def make_step(name: str, detail: str = "", status: str = "done") -> dict[str, Any]:
    return {"name": name, "detail": detail, "status": status}
