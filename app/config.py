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


def _bool_env(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "y"}


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

    # ===== 自主触发（APScheduler 定时跑，无需人工上传）=====
    scheduler_enabled: bool = field(default_factory=lambda: _bool_env("SCHEDULER_ENABLED", False))
    # 触发节奏：cron 优先（标准 5 段表达式，如 "0 9 * * *" 每天 09:00）；
    # cron 为空且 interval>0 时按分钟间隔跑；两者都没配则默认每天 09:00。
    scheduler_cron: str = field(default_factory=lambda: os.getenv("SCHEDULER_CRON", "").strip())
    scheduler_interval_minutes: int = field(default_factory=lambda: _int_env("SCHEDULER_INTERVAL_MINUTES", 0))
    scheduler_timezone: str = field(
        default_factory=lambda: os.getenv("SCHEDULER_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai"
    )
    # 数据源：当前为固定文件路径（留空回退 data/sample_orders.xlsx）。
    # 以后要扫 inbox 目录 / 接电商平台 API，只改 scheduler.resolve_order_file()，此处不动。
    scheduler_input_file: str = field(default_factory=lambda: os.getenv("SCHEDULER_INPUT_FILE", "").strip())
    scheduler_use_llm: bool = field(default_factory=lambda: _bool_env("SCHEDULER_USE_LLM", False))
    scheduler_send_wecom: bool = field(default_factory=lambda: _bool_env("SCHEDULER_SEND_WECOM", True))
    # True：自动跑完只推「待确认」通知，留人在系统里确认后再发正式日报（保留 HITL）；
    # False（默认）：自动批准直接推送，真正无人值守闭环。
    scheduler_require_review: bool = field(default_factory=lambda: _bool_env("SCHEDULER_REQUIRE_REVIEW", False))


# 全局单例（运行期不变）；测试可自行构造 Config(...) 覆盖
settings = Config()
