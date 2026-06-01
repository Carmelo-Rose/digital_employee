"""统一推送接口：企微群机器人 + 飞书自定义机器人。

两者都是「POST 一个 JSON 到 webhook」，因此用同一函数 + channel 区分。
未配置对应 URL 时返回 mock 成功，保证 Demo 不接任何真实凭证也能演示。

后续想用 AI_Agent_claude 里 SDK 版的 send_feishu_message（按 app 凭证发到
指定群/人），把 _push_feishu 换成对那个函数的调用即可。
"""
from __future__ import annotations

import httpx

from .config import Config, settings


def _push_wecom(markdown: str, url: str) -> dict:
    # 企业微信群机器人 markdown 消息（content 上限约 4096 字节，超长截断）
    payload = {"msgtype": "markdown", "markdown": {"content": markdown[:4000]}}
    resp = httpx.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return {"ok": data.get("errcode", 0) == 0, "channel": "wecom", "response": data}


def _push_feishu(markdown: str, url: str) -> dict:
    # 飞书自定义机器人：text 消息（富文本/卡片可后续升级）
    payload = {"msg_type": "text", "content": {"text": markdown[:4000]}}
    resp = httpx.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return {"ok": data.get("StatusCode", data.get("code", 0)) == 0, "channel": "feishu", "response": data}


def push_report(markdown: str, channel: str = "wecom", cfg: Config | None = None) -> dict:
    """把日报推送到指定渠道。channel: wecom | feishu。"""
    cfg = cfg or settings
    url = cfg.wecom_webhook_url if channel == "wecom" else cfg.feishu_webhook_url

    if channel not in {"wecom", "feishu"}:
        return {"ok": False, "channel": channel, "error": "未知渠道"}
    if not url:
        # 未配置 webhook → mock 成功，便于本地演示
        return {"ok": True, "mock": True, "channel": channel,
                "message": f"未配置 {channel} webhook，已模拟推送成功（{len(markdown)} 字符）"}

    try:
        return _push_wecom(markdown, url) if channel == "wecom" else _push_feishu(markdown, url)
    except Exception as e:  # noqa: BLE001 —— 推送失败不应让请求 500
        return {"ok": False, "channel": channel, "error": str(e)}
