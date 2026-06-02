"""统一推送接口：企微群机器人（markdown_v2）+ 飞书自定义机器人（interactive card）。

两种渠道均从 analysis_result dict 构建结构化卡片，不再依赖纯文本 Markdown。
未配置对应 URL 时返回 mock 成功，保证 Demo 不接任何真实凭证也能演示。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from .config import Config, settings

CATEGORY_TITLES: dict[str, str] = {
    "paid_not_shipped": "已付款未发货",
    "logistics_abnormal": "物流异常/超时",
    "refund_abnormal": "退款状态异常",
    "low_stock": "库存不足",
    "cs_keyword": "客服备注预警",
    "amount_anomaly": "订单金额异常",
}


# ── 企业微信：markdown_v2 卡片 ────────────────────────────────────────────────

def _build_wecom_card(analysis: dict[str, Any]) -> str:
    """构建企微 markdown_v2 内容（含表格、分割线、颜色标注）。"""
    date = analysis.get("date", datetime.now().strftime("%Y-%m-%d"))
    total = analysis.get("total_orders", 0)
    anomaly_orders = analysis.get("anomaly_orders", 0)
    anomaly_total = analysis.get("anomaly_total", 0)
    summary = analysis.get("summary", {})
    categories = analysis.get("categories", {})

    # 异常等级标注
    severity_icon = "🔴" if anomaly_orders > 10 else ("🟡" if anomaly_orders > 0 else "🟢")

    lines: list[str] = [
        f"# 🤖 电商运营日报 · {date}",
        "",
        f"**总订单数**：{total}　　**异常订单**：{severity_icon} {anomaly_orders} 单（共 {anomaly_total} 项异常）",
        "",
        "---",
        "",
        "## 异常分类汇总",
        "",
        "| 类别 | 数量 | 状态 |",
        "| :--- | :---: | :---: |",
    ]

    for key, title in CATEGORY_TITLES.items():
        cnt = summary.get(key, 0)
        # markdown_v2 不支持 <font color>，统一用 emoji 表达等级
        if cnt > 3:
            status = "🔴 紧急"
        elif cnt > 0:
            status = "🟡 需关注"
        else:
            status = "✅ 正常"
        lines.append(f"| {title} | {cnt} | {status} |")

    # 严重异常明细（最多各类前 3 条）
    has_detail = False
    detail_lines: list[str] = ["", "---", "", "## 严重异常明细", ""]
    for key, title in CATEGORY_TITLES.items():
        items = categories.get(key, [])
        severe = [it for it in items if it.get("严重度") == "严重"][:3]
        if severe:
            has_detail = True
            detail_lines.append(f"**{title}**")
            for it in severe:
                oid = it.get("order_id", "")
                reason = it.get("原因", "")
                detail_lines.append(f"> `{oid}` {reason}")
            detail_lines.append("")

    if has_detail:
        lines.extend(detail_lines)

    lines += ["---", f"*生成时间：{analysis.get('generated_at', '')}*"]
    return "\n".join(lines)


def _push_wecom(analysis: dict[str, Any], url: str, markdown_fallback: str = "") -> dict:
    """发送企微 markdown_v2 卡片；失败回退纯文本。"""
    content = _build_wecom_card(analysis) if analysis else markdown_fallback[:4000]
    payload = {"msgtype": "markdown_v2", "markdown_v2": {"content": content[:4096]}}
    resp = httpx.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return {"ok": data.get("errcode", 0) == 0, "channel": "wecom", "response": data}


# ── 飞书：interactive card ────────────────────────────────────────────────────

def _build_feishu_card(analysis: dict[str, Any]) -> dict:
    """构建飞书 interactive card JSON。"""
    date = analysis.get("date", datetime.now().strftime("%Y-%m-%d"))
    total = analysis.get("total_orders", 0)
    anomaly_orders = analysis.get("anomaly_orders", 0)
    anomaly_total = analysis.get("anomaly_total", 0)
    summary = analysis.get("summary", {})
    categories = analysis.get("categories", {})

    severity_color = "red" if anomaly_orders > 10 else ("yellow" if anomaly_orders > 0 else "green")
    severity_icon = "🔴" if anomaly_orders > 10 else ("🟡" if anomaly_orders > 0 else "🟢")

    elements: list[dict] = []

    # 总览区
    elements.append({
        "tag": "div",
        "fields": [
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**总订单数**\n{total} 单"}},
            {"is_short": True, "text": {"tag": "lark_md",
                                        "content": f"**异常订单**\n{severity_icon} {anomaly_orders} 单（{anomaly_total} 项）"}},
        ],
    })
    elements.append({"tag": "hr"})

    # 分类汇总
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": "**📊 异常分类汇总**"},
    })

    cat_fields: list[dict] = []
    for key, title in CATEGORY_TITLES.items():
        cnt = summary.get(key, 0)
        icon = "🔴" if cnt > 3 else ("🟡" if cnt > 0 else "✅")
        cat_fields.append({
            "is_short": True,
            "text": {"tag": "lark_md", "content": f"**{title}**\n{icon} {cnt} 单"},
        })
    # 飞书 fields 每行最多 2 列
    for i in range(0, len(cat_fields), 2):
        elements.append({"tag": "div", "fields": cat_fields[i:i + 2]})

    elements.append({"tag": "hr"})

    # 严重明细
    detail_md_lines: list[str] = ["**⚠️ 严重异常明细**\n"]
    has_severe = False
    for key, title in CATEGORY_TITLES.items():
        items = categories.get(key, [])
        severe = [it for it in items if it.get("严重度") == "严重"][:3]
        if severe:
            has_severe = True
            detail_md_lines.append(f"**{title}**")
            for it in severe:
                oid = it.get("order_id", "")
                reason = it.get("原因", "")
                detail_md_lines.append(f"• `{oid}` {reason}")
            detail_md_lines.append("")

    if has_severe:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(detail_md_lines)},
        })
        elements.append({"tag": "hr"})

    # 生成时间
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text",
                      "content": f"生成时间：{analysis.get('generated_at', '')}"}],
    })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"🤖 电商运营日报 · {date}"},
                "template": severity_color,
            },
            "elements": elements,
        },
    }


def _push_feishu(analysis: dict[str, Any], url: str, markdown_fallback: str = "") -> dict:
    """发送飞书 interactive card；无 analysis 时回退纯文本。"""
    if analysis:
        payload = _build_feishu_card(analysis)
    else:
        payload = {"msg_type": "text", "content": {"text": markdown_fallback[:4000]}}
    resp = httpx.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    ok = data.get("StatusCode", data.get("code", 0)) == 0
    return {"ok": ok, "channel": "feishu", "response": data}


# ── 统一入口 ─────────────────────────────────────────────────────────────────

def push_report(
    markdown: str,
    channel: str = "wecom",
    cfg: Config | None = None,
    analysis: dict[str, Any] | None = None,
) -> dict:
    """把日报推送到指定渠道。

    analysis 有值时走富文本卡片，无值时回退 markdown 纯文本（向后兼容）。
    channel: wecom | feishu
    """
    cfg = cfg or settings
    url = cfg.wecom_webhook_url if channel == "wecom" else cfg.feishu_webhook_url

    if channel not in {"wecom", "feishu"}:
        return {"ok": False, "channel": channel, "error": "未知渠道"}
    if not url:
        return {
            "ok": True, "mock": True, "channel": channel,
            "message": f"未配置 {channel} webhook，已模拟推送成功（{len(markdown)} 字符）",
        }

    try:
        if channel == "wecom":
            return _push_wecom(analysis or {}, url, markdown_fallback=markdown)
        return _push_feishu(analysis or {}, url, markdown_fallback=markdown)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "channel": channel, "error": str(e)}
