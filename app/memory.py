"""业务规则记忆：把用户的字段映射修正、阈值调整持久化，跨任务复用。

为什么需要：数字员工第一次把「可用余量」认错成普通列、或把「48 小时未发货」
阈值定得不合用时，用户纠正一次后，下一次分析应当自动沿用，而不是每次从零开始。
这正是这个项目最有价值的「记忆」——业务规则记忆，而非闲聊记忆。

存储（demo 级，单文件 JSON，无并发锁；多进程可换 SQLite/Redis）：
  data/memory/business_memory.json
    field_overrides: {原始列名(小写去空白): canonical 字段}  用户手工纠正的字段映射
    thresholds:      {阈值名: 数值}                         用户调整的规则阈值

设计原则：schema.py / analyzer.py 保持纯函数无 IO，记忆由「节点/路由」这层
读出后作为参数传下去（见 anomaly_analysis_node / field_mapping_node）。
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import Config, settings
from .schema import COLUMN_ALIASES

_ROOT = Path(__file__).resolve().parent.parent
_MEMORY_DIR = _ROOT / "data" / "memory"
_MEMORY_FILE = _MEMORY_DIR / "business_memory.json"

# 允许被覆盖的阈值（必须与 Config 字段名一致，replace() 才能生效）
THRESHOLD_KEYS: tuple[str, ...] = (
    "pay_no_ship_hours",
    "logistics_stale_days",
    "refund_pending_days",
    "stock_low_threshold",
)

# 合法的 canonical 字段集合（字段映射 override 的值必须在其中）
VALID_CANONICALS: frozenset[str] = frozenset(COLUMN_ALIASES)

_EMPTY: dict[str, Any] = {"field_overrides": {}, "thresholds": {}}


def _norm_col(raw: str) -> str:
    """原始列名归一化：去空白 + 小写，与 schema 的 lookup 口径一致。"""
    return str(raw).strip().lower()


# ── 读写底座 ──────────────────────────────────────────────────────────────────

def load_memory() -> dict[str, Any]:
    """读取记忆文件，缺失/损坏时返回空结构（不抛异常）。"""
    if not _MEMORY_FILE.exists():
        return {"field_overrides": {}, "thresholds": {}}
    try:
        data = json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"field_overrides": {}, "thresholds": {}}
    return {
        "field_overrides": dict(data.get("field_overrides") or {}),
        "thresholds": dict(data.get("thresholds") or {}),
    }


def _save_memory(mem: dict[str, Any]) -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _MEMORY_FILE.write_text(
        json.dumps(mem, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 字段映射 override ─────────────────────────────────────────────────────────

def get_field_overrides() -> dict[str, str]:
    """{原始列名(小写): canonical}，供 schema.resolve_* 作为最高优先级映射。"""
    return load_memory()["field_overrides"]


def set_field_override(raw_column: str, canonical: str | None) -> dict[str, str]:
    """记住/更新一条字段映射纠正。canonical 为空 → 删除该条记忆。

    canonical 非空时必须是合法 canonical 字段，否则 ValueError。
    返回更新后的全部 field_overrides。
    """
    key = _norm_col(raw_column)
    if not key:
        raise ValueError("原始列名不能为空")
    mem = load_memory()
    overrides = mem["field_overrides"]
    if not canonical:
        overrides.pop(key, None)
    else:
        if canonical not in VALID_CANONICALS:
            raise ValueError(f"未知 canonical 字段：{canonical}")
        overrides[key] = canonical
    _save_memory(mem)
    return overrides


# ── 阈值持久化 ────────────────────────────────────────────────────────────────

def get_thresholds() -> dict[str, int]:
    """{阈值名: 值}，仅含合法阈值键。"""
    th = load_memory()["thresholds"]
    return {k: int(v) for k, v in th.items() if k in THRESHOLD_KEYS}


def set_thresholds(updates: dict[str, Any]) -> dict[str, int]:
    """批量更新阈值记忆。值需为正整数；非法键忽略，非法值 ValueError。

    传入某键的值为 None/"" → 删除该条（回退到 Config 默认）。
    """
    mem = load_memory()
    th = mem["thresholds"]
    for key, val in updates.items():
        if key not in THRESHOLD_KEYS:
            continue
        if val is None or val == "":
            th.pop(key, None)
            continue
        try:
            ival = int(val)
        except (TypeError, ValueError) as e:
            raise ValueError(f"阈值 {key} 必须是整数，收到 {val!r}") from e
        if ival <= 0:
            raise ValueError(f"阈值 {key} 必须为正整数，收到 {ival}")
        th[key] = ival
    _save_memory(mem)
    return get_thresholds()


def effective_config(base: Config | None = None) -> Config:
    """把阈值记忆叠加到 Config 上，返回新实例（不改全局 settings 单例）。"""
    base = base or settings
    th = get_thresholds()
    return replace(base, **th) if th else base
