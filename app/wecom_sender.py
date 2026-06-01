"""企业微信推送（第四阶段「人工确认」按钮专用入口）。

逻辑复用 app/push.py 的 push_report(..., channel="wecom")，本模块只是按职责
取个语义化名字 + 收口企微相关的返回提示，不重复实现 HTTP 调用。
未配置 WECOM_WEBHOOK_URL 时由 push_report 返回 mock 成功，不报错。
"""
from __future__ import annotations

from .push import push_report


def send_to_wecom(markdown: str) -> dict:
    """把 Markdown 日报推送到企业微信群机器人。

    返回 dict：
    - 成功真推：{"ok": True, "channel": "wecom", "response": ...}
    - 未配 webhook：{"ok": True, "mock": True, "channel": "wecom", "message": ...}
    - 失败：{"ok": False, "channel": "wecom", "error": ...}
    """
    return push_report(markdown, channel="wecom")
