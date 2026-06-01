"""集中配置：从 .env 读取，提供默认值。

所有分析阈值、关键词、推送/LLM 凭证都在这里收口，
analyzer / llm / push 只依赖 Config，不直接读环境变量，便于测试时替换。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 加载项目根目录的 .env（存在才加载，缺失不报错）
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

DATA_DIR = _ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
STATIC_DIR = _ROOT / "static"
SAMPLE_CSV = DATA_DIR / "sample_orders.csv"


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# 客服备注关键词 → 归类标签
DEFAULT_CS_KEYWORDS: dict[str, str] = {
    "投诉": "投诉",
    "催发货": "催发货",
    "催发": "催发货",
    "质量问题": "质量问题",
    "质量": "质量问题",
    "退款": "退款诉求",
    "差评": "投诉",
    "假货": "质量问题",
}


@dataclass
class Config:
    # 分析阈值
    pay_no_ship_hours: int = field(default_factory=lambda: _int_env("PAY_NO_SHIP_HOURS", 48))
    logistics_stale_days: int = field(default_factory=lambda: _int_env("LOGISTICS_STALE_DAYS", 3))
    refund_pending_days: int = field(default_factory=lambda: _int_env("REFUND_PENDING_DAYS", 2))
    stock_low_threshold: int = field(default_factory=lambda: _int_env("STOCK_LOW_THRESHOLD", 5))
    cs_keywords: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CS_KEYWORDS))

    # LLM
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock").strip() or "mock")
    # Anthropic 兼容端点（MiMo / Claude 共用）：base_url + key + model
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "mimo-v2.5"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    dashscope_api_key: str = field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", ""))

    # 推送
    wecom_webhook_url: str = field(default_factory=lambda: os.getenv("WECOM_WEBHOOK_URL", ""))
    feishu_webhook_url: str = field(default_factory=lambda: os.getenv("FEISHU_WEBHOOK_URL", ""))

    # 报告中每类异常最多展示多少行明细
    report_max_rows: int = 20


# 全局单例（运行期不变）；测试可自行构造 Config(...) 覆盖
settings = Config()
