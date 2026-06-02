"""核心：订单异常检测。

设计为纯函数、无 IO，便于以后被 AI_Agent_claude 的 Agent 直接 import 当 tool 调用。
输入规整后的 DataFrame（canonical 列名），输出结构化字典。
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .config import Config, settings
from .schema import KEY_FIELDS, normalize

# 五类异常的稳定 key 与中文标题
CATEGORIES: dict[str, str] = {
    "paid_not_shipped": "已付款未发货",
    "logistics_abnormal": "物流异常/超时",
    "refund_abnormal": "退款状态异常",
    "low_stock": "库存不足",
    "cs_keyword": "客服备注预警",
    "amount_anomaly": "订单金额异常",
}


def _has(df: pd.DataFrame, *cols: str) -> bool:
    return all(c in df.columns for c in cols)


def _row_id(row: pd.Series, idx: int) -> str:
    val = str(row.get("order_id", "")).strip()
    return val if val else f"第{idx + 1}行"


def _check_paid_not_shipped(df: pd.DataFrame, cfg: Config, now: datetime) -> tuple[list[dict], str | None]:
    if not _has(df, "pay_status", "ship_status"):
        return [], "缺少 支付状态/发货状态 列"
    items: list[dict] = []
    has_pay_time = "pay_time" in df.columns
    for idx, row in df.iterrows():
        if "已付款" not in str(row["pay_status"]):
            continue
        ship = str(row["ship_status"])
        if "未发货" not in ship and "部分发货" not in ship:
            continue
        severity, hours = "中", None
        if has_pay_time and pd.notna(row["pay_time"]):
            hours = round((now - row["pay_time"]).total_seconds() / 3600, 1)
            if hours > cfg.pay_no_ship_hours:
                severity = "严重"
        items.append({
            "order_id": _row_id(row, idx),
            "原因": f"已付款但{ship}" + (f"，付款已 {hours} 小时" if hours is not None else ""),
            "严重度": severity,
            "关键值": ship,
        })
    return items, None


def _check_logistics(df: pd.DataFrame, cfg: Config, now: datetime) -> tuple[list[dict], str | None]:
    if not _has(df, "logistics_status"):
        return [], "缺少 物流状态 列"
    bad_states = ("物流异常", "退回", "超时", "异常")
    items: list[dict] = []
    has_update = "logistics_update_time" in df.columns
    has_ship = "ship_status" in df.columns
    for idx, row in df.iterrows():
        status = str(row["logistics_status"])
        reason = severity = None
        if any(b in status for b in bad_states):
            reason, severity = f"物流状态：{status}", "严重"
        elif has_update and pd.notna(row["logistics_update_time"]):
            shipped = (not has_ship) or ("已发货" in str(row["ship_status"]))
            stale_days = (now - row["logistics_update_time"]).days
            if shipped and stale_days > cfg.logistics_stale_days:
                reason, severity = f"物流 {stale_days} 天无更新", "中"
        if reason:
            items.append({
                "order_id": _row_id(row, idx),
                "原因": reason,
                "严重度": severity,
                "关键值": status,
            })
    return items, None


def _check_refund(df: pd.DataFrame, cfg: Config, now: datetime) -> tuple[list[dict], str | None]:
    if not _has(df, "refund_status"):
        return [], "缺少 退款状态 列"
    items: list[dict] = []
    has_apply = "refund_apply_time" in df.columns
    for idx, row in df.iterrows():
        status = str(row["refund_status"])
        reason = severity = None
        if "退款失败" in status or "异常" in status:
            reason, severity = f"退款状态：{status}", "严重"
        elif "退款中" in status and has_apply and pd.notna(row["refund_apply_time"]):
            days = (now - row["refund_apply_time"]).days
            if days > cfg.refund_pending_days:
                reason, severity = f"退款中已 {days} 天未完成", "中"
        if reason:
            items.append({
                "order_id": _row_id(row, idx),
                "原因": reason,
                "严重度": severity,
                "关键值": status,
            })
    return items, None


def _check_stock(df: pd.DataFrame, cfg: Config, now: datetime) -> tuple[list[dict], str | None]:
    if not _has(df, "stock"):
        return [], "缺少 库存 列"
    items: list[dict] = []
    has_qty = "quantity" in df.columns
    for idx, row in df.iterrows():
        stock = row["stock"]
        if pd.isna(stock):
            continue
        stock = float(stock)
        qty = float(row["quantity"]) if has_qty and pd.notna(row.get("quantity")) else None
        reason = severity = None
        if stock <= 0:
            reason, severity = f"库存为 {int(stock)}", "严重"
        elif qty is not None and stock < qty:
            reason, severity = f"库存 {int(stock)} < 本单数量 {int(qty)}", "严重"
        elif stock <= cfg.stock_low_threshold:
            reason, severity = f"库存偏低（{int(stock)} ≤ {cfg.stock_low_threshold}）", "中"
        if reason:
            items.append({
                "order_id": _row_id(row, idx),
                "原因": reason + (f"，商品：{row['product_name']}" if "product_name" in df.columns else ""),
                "严重度": severity,
                "关键值": int(stock),
            })
    return items, None


def _check_cs_keyword(df: pd.DataFrame, cfg: Config, now: datetime) -> tuple[list[dict], str | None]:
    if not _has(df, "cs_note"):
        return [], "缺少 客服备注 列"
    items: list[dict] = []
    for idx, row in df.iterrows():
        note = str(row["cs_note"])
        if not note:
            continue
        hits = sorted({label for kw, label in cfg.cs_keywords.items() if kw in note})
        if hits:
            items.append({
                "order_id": _row_id(row, idx),
                "原因": f"命中关键词：{'、'.join(hits)}",
                "严重度": "严重" if "投诉" in hits or "质量问题" in hits else "中",
                "关键值": note[:40],
            })
    return items, None


def _check_amount(df: pd.DataFrame, cfg: Config, now: datetime) -> tuple[list[dict], str | None]:
    """订单金额异常：金额 ≤ 0 或缺失/无法解析。"""
    if not _has(df, "amount"):
        return [], "缺少 订单金额 列"
    items: list[dict] = []
    for idx, row in df.iterrows():
        amt = row["amount"]
        if pd.isna(amt):
            items.append({
                "order_id": _row_id(row, idx),
                "原因": "订单金额缺失/无法解析",
                "严重度": "中",
                "关键值": "",
            })
        elif float(amt) <= 0:
            items.append({
                "order_id": _row_id(row, idx),
                "原因": f"订单金额异常：{amt}",
                "严重度": "严重",
                "关键值": float(amt),
            })
    return items, None


_CHECKS = {
    "paid_not_shipped": _check_paid_not_shipped,
    "logistics_abnormal": _check_logistics,
    "refund_abnormal": _check_refund,
    "low_stock": _check_stock,
    "cs_keyword": _check_cs_keyword,
    "amount_anomaly": _check_amount,
}


def analyze_orders(
    df: pd.DataFrame,
    cfg: Config | None = None,
    now: datetime | None = None,
    *,
    already_normalized: bool = False,
    field_overrides: dict[str, str] | None = None,
) -> dict:
    """对订单 DataFrame 做五类异常检测，返回结构化结果。

    df: 原始或已规整的订单表。
    already_normalized: True 表示 df 已是 canonical 列名（测试用）。
    field_overrides: 用户记忆的字段映射纠正（{原始列名小写: canonical}），
        由调用方从 memory 层读出后传入，保持本模块无 IO。
    """
    cfg = cfg or settings
    now = now or datetime.now()
    orig_cols = [str(c) for c in df.columns]
    if already_normalized:
        ndf, resolved, missing = df, {c: c for c in df.columns}, []
    else:
        ndf, resolved, missing = normalize(df, field_overrides)

    categories: dict[str, list[dict]] = {}
    skipped: list[str] = []        # 人读的「类别：原因」
    skipped_keys: list[str] = []   # 结构化：被跳过检测的 category key
    for key, fn in _CHECKS.items():
        items, skip_reason = fn(ndf, cfg, now)
        categories[key] = items
        if skip_reason:
            skipped.append(f"{CATEGORIES[key]}：{skip_reason}")
            skipped_keys.append(key)

    summary = {key: len(items) for key, items in categories.items()}
    # 一个订单可能同时命中多类异常；distinct 用于计算异常率，避免 >100%
    distinct_orders = {it["order_id"] for items in categories.values() for it in items}
    recognized = list(resolved.keys())
    unrecognized = [c for c in orig_cols if c not in set(resolved.values())]
    key_missing = [c for c in KEY_FIELDS if c not in resolved]
    return {
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "total_orders": int(len(ndf)),
        "anomaly_total": int(sum(summary.values())),       # 异常项数（含重复订单）
        "anomaly_orders": len(distinct_orders),            # 去重后的异常订单数
        "summary": summary,
        "category_titles": CATEGORIES,
        "categories": categories,
        "recognized_columns": recognized,                  # canonical 名
        "unrecognized_columns": unrecognized,              # 上传里没映射上的原始列
        "key_missing": key_missing,                        # 缺失的关键字段
        "skipped_checks": skipped,
        "skipped_keys": skipped_keys,
    }
