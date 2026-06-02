"""订单数据列定义与容错映射（兼容层）。

业务逻辑已迁移至 app/domains/ecommerce.py（EcommerceDomain）。
本文件保留供外部脚本（run_stage3.py 等）直接调用，不在工作流节点中使用。
真实导出文件的表头千差万别（淘宝/抖店/拼多多/英文系统），
这里用「canonical 字段 → 中文默认表头 + 别名集合」做识别，
analyzer 只认 canonical 名，从而与具体平台解耦。
"""
from __future__ import annotations

import pandas as pd

# canonical 字段 -> 可能出现的列名（含默认中文表头，全部小写化后比较）
# 每个 canonical 的第一个别名为「中文展示标签」，用于数据质量提示等场景。
COLUMN_ALIASES: dict[str, list[str]] = {
    "order_id": ["订单号", "订单编号", "订单id", "order_id", "order_no"],
    "store_name": ["店铺名称", "店铺", "门店", "store_name", "shop_name"],
    "pay_status": ["支付状态", "付款状态", "payment_status", "pay_status"],
    "pay_time": ["支付时间", "付款时间", "pay_time", "payment_time"],
    "ship_status": ["发货状态", "shipping_status", "ship_status"],
    "ship_time": ["发货时间", "ship_time"],
    "logistics_status": ["物流状态", "快递状态", "logistics_status"],
    "logistics_update_time": ["物流更新时间", "最近物流时间", "logistics_update_time"],
    "refund_status": ["退款状态", "refund_status"],
    "refund_apply_time": ["退款申请时间", "refund_apply_time"],
    "sku": ["商品SKU", "sku", "货号"],
    "product_name": ["商品名称", "宝贝名称", "product_name"],
    "quantity": ["购买数量", "数量", "quantity", "qty"],
    "stock": ["库存", "库存数量", "可用库存", "stock", "stock_qty"],
    "amount": ["订单金额", "实付金额", "amount", "total_amount"],
    "cs_note": ["客服备注", "备注", "留言", "cs_note", "customer_note", "remark"],
}

# canonical -> 中文展示标签（取第一个别名）
CANONICAL_LABELS: dict[str, str] = {k: v[0] for k, v in COLUMN_ALIASES.items()}

# 关键字段：缺失则在数据质量提示里告警（分析结果可能不完整）
KEY_FIELDS: list[str] = ["order_id", "pay_status", "ship_status"]

# 这些列若缺失，对应异常检测会被跳过（而非报错）
TIME_COLUMNS = {"pay_time", "ship_time", "logistics_update_time", "refund_apply_time"}
NUMERIC_COLUMNS = {"quantity", "stock", "amount"}


def _apply_overrides(
    resolved: dict[str, str],
    lookup: dict[str, Any],
    overrides: dict[str, str] | None,
) -> dict[str, str]:
    """把用户的字段映射纠正叠加到别名识别结果上（用户纠正优先级最高）。

    overrides: {原始列名(小写去空白): canonical}，由 memory 层读出后传入；
    schema 自身保持纯函数、不读文件。命中当前表才生效。
    """
    if not overrides:
        return resolved
    for raw_lower, canonical in overrides.items():
        if canonical and raw_lower in lookup:
            resolved[canonical] = lookup[raw_lower]
    return resolved


def resolve_column_names(columns, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """从列名列表解析 {canonical: 原始列名}（供 LangGraph FieldMappingNode 复用）。"""
    lookup = {str(c).strip().lower(): str(c) for c in columns}
    resolved: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lookup:
                resolved[canonical] = lookup[alias.lower()]
                break
    return _apply_overrides(resolved, lookup, overrides)


def resolve_columns(df: pd.DataFrame, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """返回 {canonical: 原始列名}，只包含在 df 中实际找到的字段。"""
    lookup = {str(c).strip().lower(): c for c in df.columns}
    resolved: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lookup:
                resolved[canonical] = lookup[alias.lower()]
                break
    return _apply_overrides(resolved, lookup, overrides)


def normalize(
    df: pd.DataFrame, overrides: dict[str, str] | None = None
) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """把原始 df 规整为 canonical 列名的新 df。

    返回 (规整后的 df, 列映射, 缺失的 canonical 字段列表)。
    时间列转 datetime（解析失败置 NaT），数值列转数字（失败置 NaN）。
    """
    resolved = resolve_columns(df, overrides)
    out = pd.DataFrame()
    for canonical, original in resolved.items():
        out[canonical] = df[original]

    for col in TIME_COLUMNS & set(out.columns):
        out[col] = pd.to_datetime(out[col], errors="coerce")
    for col in NUMERIC_COLUMNS & set(out.columns):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    # 文本列统一成去空白的字符串，NaN -> ""
    for col in set(out.columns) - TIME_COLUMNS - NUMERIC_COLUMNS:
        out[col] = out[col].fillna("").astype(str).str.strip()

    missing = [c for c in COLUMN_ALIASES if c not in resolved]
    return out, resolved, missing
