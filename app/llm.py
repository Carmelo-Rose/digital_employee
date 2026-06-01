"""LLM 洞察接口（provider-agnostic）。

第一版默认 MockLLM：用分析数字拼出结构化的运营洞察+建议，不依赖任何外部 API。
后续接真模型时，只需实现 summarize() 并在 get_llm_client() 里按 LLM_PROVIDER 返回。
"""
from __future__ import annotations

from typing import Protocol

from .config import Config, settings


class LLMClient(Protocol):
    def summarize(self, analysis: dict) -> str:  # noqa: D401
        """根据分析结果生成一段中文运营洞察（Markdown 段落）。"""
        ...

    def complete(self, prompt: str, system: str | None = None) -> str:  # noqa: D401
        """通用自由文本补全（供 llm_reporter 生成整篇 AI 日报用）。"""
        ...


class MockLLM:
    """无需联网的占位实现：基于规则把数字翻译成人话。"""

    def complete(self, prompt: str, system: str | None = None) -> str:
        # mock 不做自由生成；整篇 AI 日报的 mock 版由 llm_reporter._mock_report 负责。
        raise RuntimeError("MockLLM 不支持自由补全，请改用 llm_reporter 的 mock 渲染")

    def summarize(self, analysis: dict) -> str:
        s = analysis["summary"]
        titles = analysis["category_titles"]
        total = analysis["total_orders"]
        anomaly_orders = analysis.get("anomaly_orders", analysis["anomaly_total"])
        rate = (anomaly_orders / total * 100) if total else 0

        # 找出最突出的异常类别
        ranked = sorted(s.items(), key=lambda kv: kv[1], reverse=True)
        top = [f"{titles[k]}（{v} 单）" for k, v in ranked if v > 0][:3]

        lines = [
            f"本批共 **{total}** 笔订单，其中 **{anomaly_orders}** 笔存在异常，异常率 **{rate:.1f}%**。",
        ]
        if top:
            lines.append(f"最需关注：{ '、'.join(top) }。")
        else:
            lines.append("未发现明显异常，运营状况良好。")

        # 针对性建议
        advice = []
        if s.get("paid_not_shipped"):
            advice.append("尽快推动仓库对「已付款未发货」订单出库，优先处理超时单，避免投诉与超时赔付。")
        if s.get("logistics_abnormal"):
            advice.append("联系物流商核实「物流异常/超时」包裹，必要时主动安抚买家。")
        if s.get("refund_abnormal"):
            advice.append("客服跟进「退款异常」工单，防止纠纷升级与平台介入。")
        if s.get("low_stock"):
            advice.append("及时补货「库存不足」商品，必要时下架防止超卖。")
        if s.get("cs_keyword"):
            advice.append("逐条回访「客服备注预警」订单，投诉/质量类需当日响应。")
        if advice:
            lines.append("**行动建议：**")
            lines.extend(f"{i}. {a}" for i, a in enumerate(advice, 1))
        return "\n".join(lines)


_SYSTEM_PROMPT = (
    "你是一名资深电商运营专家。基于给定的订单异常分析数据，用简洁专业的中文写一段运营洞察，"
    "包含：1) 整体健康度判断（异常率、最突出的风险）；2) 按优先级排序的具体行动建议（谁该做什么）。"
    "用 Markdown，控制在 200 字以内，不要复述原始数字表格，直接给判断和建议。"
)


def _build_user_prompt(analysis: dict) -> str:
    """把分析结果压成紧凑文本喂给模型（只给摘要 + 每类少量样例，控制 token）。"""
    titles = analysis["category_titles"]
    lines = [
        f"订单总数：{analysis['total_orders']}",
        f"异常订单数（去重）：{analysis.get('anomaly_orders', analysis['anomaly_total'])}",
        "各类异常计数与样例：",
    ]
    for key, title in titles.items():
        items = analysis["categories"].get(key, [])
        if not items:
            lines.append(f"- {title}：0")
            continue
        examples = "；".join(it["原因"] for it in items[:3])
        lines.append(f"- {title}：{len(items)}（例：{examples}）")
    if analysis.get("skipped_checks"):
        lines.append("注意，以下检测因缺列被跳过：" + "；".join(analysis["skipped_checks"]))
    return "\n".join(lines)


class AnthropicLLM:
    """走 Anthropic 兼容端点的真实实现（MiMo-V2.5 / Claude 共用）。

    失败时自动回退 MockLLM，保证日报生成永不中断。
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._fallback = MockLLM()
        self._client = None
        try:
            import anthropic  # 延迟导入，未装也不影响 mock
            kwargs = {"api_key": cfg.llm_api_key}
            if cfg.llm_base_url:
                kwargs["base_url"] = cfg.llm_base_url
            self._client = anthropic.Anthropic(**kwargs)
        except Exception:  # noqa: BLE001
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None and bool(self.cfg.llm_api_key)

    def complete(self, prompt: str, system: str | None = None) -> str:
        """通用补全：直接调模型返回文本。不可用时抛异常，由调用方决定回退。"""
        if not self.available:
            raise RuntimeError("LLM 客户端不可用（缺 anthropic 包或 API Key）")
        kwargs: dict = {
            "model": self.cfg.llm_model,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = [{
                "type": "text", "text": system,
                "cache_control": {"type": "ephemeral"},  # system 固定，开缓存省 token
            }]
        msg = self._client.messages.create(**kwargs)
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

    def summarize(self, analysis: dict) -> str:
        if not self.available:
            return self._fallback.summarize(analysis)
        try:
            text = self.complete(_build_user_prompt(analysis), system=_SYSTEM_PROMPT)
            return text or self._fallback.summarize(analysis)
        except Exception as e:  # noqa: BLE001 —— 模型不可用时不阻断日报
            return self._fallback.summarize(analysis) + f"\n\n> _（实时洞察暂不可用，已回退规则版：{e}）_"


def get_llm_client(cfg: Config | None = None) -> LLMClient:
    cfg = cfg or settings
    provider = cfg.llm_provider.lower()
    # mimo / claude / anthropic 都走 Anthropic 兼容端点
    if provider in {"mimo", "claude", "anthropic"}:
        return AnthropicLLM(cfg)
    # openai / qwen 暂未实现，回退 mock（接入位见上方注释约定）
    return MockLLM()
