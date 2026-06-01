"""订单文件读取（CSV/Excel）单一入口。

抽出来供 Web 路由 / CLI / 未来其他入口共用，避免重复实现编码兜底。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_orders_table(path: str | Path) -> pd.DataFrame:
    """读 CSV/Excel 为 DataFrame。CSV 编码 utf-8 失败回退 gbk（中文导出常见）。"""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        try:
            return pd.read_csv(p)
        except UnicodeDecodeError:
            return pd.read_csv(p, encoding="gbk")
    return pd.read_excel(p)  # openpyxl 读 .xlsx/.xls
