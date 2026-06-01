"""FileParseNode：读取 Excel/CSV，产出总行数 / 预览 / 原始字段 / records。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..agent_state import AgentState
from ..loader import read_orders_table
from ._common import make_step

_ALLOWED = {".csv", ".xlsx", ".xls"}


def file_parse_node(state: AgentState) -> dict[str, Any]:
    path = state.get("file_path")
    name = state.get("file_name") or (Path(path).name if path else "未知文件")
    try:
        if not path or not Path(path).exists():
            raise FileNotFoundError("文件不存在")
        if Path(path).suffix.lower() not in _ALLOWED:
            raise ValueError(f"不支持的文件格式：{Path(path).suffix or '未知'}")
        df = read_orders_table(path)
        if df.empty or len(df.columns) == 0:
            raise ValueError("文件为空或没有有效数据行")

        raw_columns = [str(c) for c in df.columns]
        preview = df.head(5).fillna("").astype(str).to_dict(orient="records")
        # NaN -> None，保留原始类型供后续 analyzer 重新规整
        records = df.where(pd.notna(df), None).to_dict(orient="records")
        return {
            "raw_columns": raw_columns,
            "total_rows": int(len(df)),
            "preview_rows": preview,
            "dataframe_records": records,
            "steps": [make_step("读取订单数据", f"成功读取 {len(df)} 行订单，{len(raw_columns)} 个字段")],
        }
    except Exception as e:  # noqa: BLE001 —— 错误以步骤+errors 形式返回，不抛
        return {
            "errors": [f"文件解析失败：{e}"],
            "steps": [make_step("读取订单数据", str(e), status="error")],
        }
