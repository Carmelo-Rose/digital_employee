"""业务规则记忆测试：字段映射 override（纯函数）+ 阈值持久化（隔离临时文件）。"""
from __future__ import annotations

import pandas as pd
import pytest

from app import memory
from app.schema import resolve_columns


@pytest.fixture
def isolated_memory(tmp_path, monkeypatch):
    """把记忆文件指到临时目录，避免污染真实 data/memory。"""
    f = tmp_path / "business_memory.json"
    monkeypatch.setattr(memory, "_MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory, "_MEMORY_FILE", f)
    return f


# ── 字段映射 override（schema 层纯函数，无 IO）────────────────────────────────

def test_override_maps_unrecognized_column():
    df = pd.DataFrame({"订单号": ["A1"], "可用余量": [3]})
    # 无 override：可用余量 不被识别成 stock
    assert "stock" not in resolve_columns(df)
    # 给定 override：可用余量 → stock 生效
    resolved = resolve_columns(df, {"可用余量": "stock"})
    assert resolved["stock"] == "可用余量"


def test_override_takes_priority_over_alias():
    df = pd.DataFrame({"库存": [10], "可用库存": [5]})
    # 别名识别默认命中「库存」；override 强制改用「可用库存」
    resolved = resolve_columns(df, {"可用库存": "stock"})
    assert resolved["stock"] == "可用库存"


# ── 记忆读写（隔离临时文件）───────────────────────────────────────────────────

def test_set_and_get_field_override(isolated_memory):
    memory.set_field_override("可用余量", "stock")
    assert memory.get_field_overrides() == {"可用余量": "stock"}
    # 留空 → 删除
    memory.set_field_override("可用余量", None)
    assert memory.get_field_overrides() == {}


def test_invalid_canonical_rejected(isolated_memory):
    with pytest.raises(ValueError):
        memory.set_field_override("某列", "不存在的字段")


def test_thresholds_persist_and_apply(isolated_memory):
    memory.set_thresholds({"pay_no_ship_hours": 24, "stock_low_threshold": 3})
    assert memory.get_thresholds() == {"pay_no_ship_hours": 24, "stock_low_threshold": 3}
    cfg = memory.effective_config()
    assert cfg.pay_no_ship_hours == 24
    assert cfg.stock_low_threshold == 3


def test_threshold_validation(isolated_memory):
    with pytest.raises(ValueError):
        memory.set_thresholds({"pay_no_ship_hours": -1})
    with pytest.raises(ValueError):
        memory.set_thresholds({"pay_no_ship_hours": "abc"})
    # 非法键被忽略，不报错
    assert memory.set_thresholds({"unknown_key": 5}) == {}
