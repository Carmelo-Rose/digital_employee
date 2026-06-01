"""LLM 运营日报生成模块（第三阶段）。

把 analyzer.py 的结构化规则结果，写成一份「像运营人员写的」AI 数字员工日报，
固定 7 个板块：今日订单概况 / 重点异常问题 / 需要优先处理的订单 /
商品·库存风险 / 客服备注风险 / AI 运营建议 / 明日关注事项。

不重复造轮子（与现有模块的分工）：
- 规则分析仍由 analyzer.py 负责，本模块只把数据「写成话」。
- mock / 真实 API / provider 选择 / env Key / MiMo 端点 全部复用 app/llm.py
  与 app/config.py，本模块不重复实现密钥管理与 HTTP 调用。
- mock 模式（默认、不依赖真实 API）由本模块的 _mock_report 确定性渲染；
  真实模式调用 llm.get_llm_client().complete(...)，失败自动回退 mock。
"""
from __future__ import annotations

from .config import Config, settings
from .llm import AnthropicLLM, get_llm_client
from .report import data_quality_md

# 7 个板块标题（顺序即输出顺序）
SECTIONS = [
    "今日订单概况",
    "重点异常问题",
    "需要优先处理的订单",
    "商品 / 库存风险",
    "客服备注风险",
    "AI 运营建议",
    "明日关注事项",
]

_SYSTEM_PROMPT = (
    "你是一名经验丰富的电商运营负责人，每天给团队写运营日报。"
    "我会给你今天订单的结构化异常分析数据，请你写成一份自然、专业、有判断力的中文运营日报，"
    "语气像真人运营负责人在跟团队交代工作，不要像机器罗列统计。"
    "必须且只能包含以下 7 个二级标题板块（顺序一致，用 Markdown 的 ## ）："
    + "、".join(SECTIONS) + "。"
    "核心要求（这是日报的价值所在）："
    "1) 明确指出异常主要集中在哪个环节（发货 / 物流 / 退款 / 库存 / 客诉）；"
    "2) 判断哪类问题优先级最高、为什么；"
    "3) 区分『今天必须处理』和『可以次日观察』的事项，分别放进对应板块；"
    "4) 点名具体订单号，「AI 运营建议」给可执行动作并指明责任方（仓储/客服/采购等）。"
    "约束：不要堆砌原始表格；不要编造数据里没有的数字；"
    "对于数据中标注『未识别 / 未参与分析』的字段，不要凭空给出该维度的风险结论。"
    "不要写一级大标题（# 开头），直接从第一个 ## 板块开始输出。"
)


def _severe_items(analysis: dict) -> list[dict]:
    """跨类别收集「严重」级订单，按订单号去重，保留首个原因。"""
    seen: dict[str, dict] = {}
    titles = analysis["category_titles"]
    for key, items in analysis["categories"].items():
        for it in items:
            if it.get("严重度") == "严重":
                oid = it["order_id"]
                if oid not in seen:
                    seen[oid] = {"order_id": oid, "类别": titles[key], "原因": it["原因"]}
    return list(seen.values())


def _build_prompt(analysis: dict) -> str:
    """把分析结果压成紧凑文本喂给模型（摘要 + 每类样例 + 严重订单清单）。"""
    titles = analysis["category_titles"]
    lines = [
        f"日期：{analysis['date']}",
        f"订单总数：{analysis['total_orders']}",
        f"异常订单数（去重）：{analysis.get('anomaly_orders', analysis['anomaly_total'])}",
        "",
        "各类异常计数与样例：",
    ]
    for key, title in titles.items():
        items = analysis["categories"].get(key, [])
        if not items:
            lines.append(f"- {title}：0")
            continue
        ex = "；".join(f"{it['order_id']}（{it['原因']}）" for it in items[:5])
        lines.append(f"- {title}：{len(items)}，例：{ex}")
    severe = _severe_items(analysis)
    if severe:
        lines.append("")
        lines.append("严重级订单（建议优先处理）：")
        lines.extend(f"- {s['order_id']}｜{s['类别']}｜{s['原因']}" for s in severe[:15])
    if analysis.get("skipped_checks"):
        lines.append("")
        lines.append("以下检测因缺列被跳过：" + "；".join(analysis["skipped_checks"]))
    return "\n".join(lines)


# 业务元数据：每类异常归属环节、优先级、影响判断（驱动 mock 的业务判断文案）
_CAT_META: dict[str, dict[str, str]] = {
    "paid_not_shipped": {"env": "履约", "prio": "高", "why": "付款未发货易触发超时赔付与差评"},
    "logistics_abnormal": {"env": "履约", "prio": "高", "why": "物流异常/超时直接影响签收体验"},
    "refund_abnormal": {"env": "售后", "prio": "高", "why": "退款失败/异常涉及资金安全与平台介入"},
    "amount_anomaly": {"env": "交易", "prio": "高", "why": "金额异常可能是错单、改价或营销漏洞"},
    "cs_keyword": {"env": "口碑", "prio": "高", "why": "投诉/质量类备注须当天回访安抚"},
    "low_stock": {"env": "商品", "prio": "中", "why": "库存不足影响后续履约，需补货跟进"},
}


# ---------------------------------------------------------------------------
# mock 渲染：不依赖任何 API，确定性产出 7 板块 AI 风格日报（含业务判断）
# ---------------------------------------------------------------------------
def _mock_report(analysis: dict) -> str:
    titles = analysis["category_titles"]
    cats = analysis["categories"]
    s = analysis["summary"]
    total = analysis["total_orders"]
    anomaly = analysis.get("anomaly_orders", analysis["anomaly_total"])
    rate = (anomaly / total * 100) if total else 0
    health = "良好" if rate < 20 else ("需关注" if rate < 50 else "风险偏高")

    def lst(key: str, n: int = 8) -> list[str]:
        return [f"- `{it['order_id']}`：{it['原因']}" for it in cats.get(key, [])[:n]]

    out: list[str] = [f"# 🤖 AI 运营日报 · {analysis['date']}", ""]

    # ① 今日订单概况：按业务环节归并，点明「主战场」
    out += [f"## {SECTIONS[0]}", ""]
    out.append(
        f"今天共处理 **{total}** 笔订单，其中 **{anomaly}** 笔存在异常，异常率约 **{rate:.1f}%**，"
        f"整体运营健康度 **{health}**。"
    )
    env_sum: dict[str, int] = {}
    for k, v in s.items():
        if v > 0 and k in _CAT_META:
            env_sum[_CAT_META[k]["env"]] = env_sum.get(_CAT_META[k]["env"], 0) + v
    if env_sum:
        ranked_env = sorted(env_sum.items(), key=lambda kv: -kv[1])
        top_env, top_n = ranked_env[0]
        rest = "、".join(f"{e}（{n} 项）" for e, n in ranked_env[1:3])
        line = f"从环节看，问题主要集中在 **{top_env}环节**（{top_n} 项）"
        line += f"，其次是 {rest}" if rest else ""
        out.append(line + "，应作为今天运营的主战场。")
    else:
        out.append("今日未发现明显异常，运营状态平稳，按常规节奏运营即可。")
    out.append("")

    # ② 重点异常问题：按优先级分级，区分今天必处理 / 次日跟进
    out += [f"## {SECTIONS[1]}", ""]
    nonzero = [(k, v) for k, v in s.items() if v > 0]
    if not nonzero:
        out += ["今日无突出异常问题，保持常规运营节奏即可。", ""]
    else:
        high = sorted([kv for kv in nonzero if _CAT_META.get(kv[0], {}).get("prio") == "高"], key=lambda kv: -kv[1])
        mid = sorted([kv for kv in nonzero if _CAT_META.get(kv[0], {}).get("prio") != "高"], key=lambda kv: -kv[1])
        if high:
            out.append("**🔴 高优先（今天必须处理）**")
            out += [f"- **{titles[k]}**（{v} 单）：{_CAT_META[k]['why']}。" for k, v in high]
        if mid:
            out.append("")
            out.append("**🟡 中优先（可次日跟进观察）**")
            out += [f"- **{titles[k]}**（{v} 单）：{_CAT_META.get(k, {}).get('why', '持续观察')}。" for k, v in mid]
        out.append("")

    # ③ 需要优先处理的订单：严重级清单 + 优先级判断
    out += [f"## {SECTIONS[2]}", ""]
    severe = _severe_items(analysis)
    if severe:
        out.append(f"按「履约 > 售后 / 口碑 > 商品」的优先级，今天先清以下 **{len(severe)}** 笔严重级订单：")
        out += [f"- `{x['order_id']}`（{x['类别']}）：{x['原因']}" for x in severe[:12]]
        if len(severe) > 12:
            out.append(f"- …另有 {len(severe) - 12} 笔严重订单")
    else:
        out.append("当前无严重级订单，按常规节奏处理异常即可。")
    out.append("")

    skipped_keys = set(analysis.get("skipped_keys", []))

    out += [f"## {SECTIONS[3]}", ""]
    if "low_stock" in skipped_keys:
        out.append("未识别库存字段，本次未进行库存风险分析。")
    else:
        stock_items = lst("low_stock")
        out += (["库存存在以下风险，需补货或下架防超卖："] + stock_items) if stock_items else ["商品库存暂无明显风险。"]
    out.append("")

    out += [f"## {SECTIONS[4]}", ""]
    if "cs_keyword" in skipped_keys:
        out.append("未识别客服备注字段，本次未进行客服备注风险分析。")
    else:
        cs_items = lst("cs_keyword")
        out += (["客服备注命中风险关键词，需逐条回访："] + cs_items) if cs_items else ["客服备注未见风险关键词。"]
    out.append("")

    # ⑥ AI 运营建议：高优先（履约/售后/交易/口碑）在前，中优先（库存）在后
    out += [f"## {SECTIONS[5]}", ""]
    advice = []
    if s.get("paid_not_shipped"):
        advice.append("**仓储**：今日清理「已付款未发货」积压，超时单优先出库，避免超时赔付与投诉。")
    if s.get("logistics_abnormal"):
        advice.append("**物流对接**：核实异常/超时包裹轨迹，主动向买家同步进度安抚情绪。")
    if s.get("refund_abnormal"):
        advice.append("**客服**：跟进退款失败/异常工单，及时处置防止平台介入与纠纷升级。")
    if s.get("amount_anomaly"):
        advice.append("**交易 / 财务**：核对订单金额异常单，排查错单、改价或营销漏洞，避免资损。")
    if s.get("cs_keyword"):
        advice.append("**客服主管**：投诉 / 质量类备注当日响应，建立回访闭环。")
    if s.get("low_stock"):
        advice.append("**采购**：对低库存与缺货商品补货，必要时临时下架防超卖（可次日跟进）。")
    out += [f"{i}. {a}" for i, a in enumerate(advice, 1)] if advice else ["1. 保持当前运营节奏，关注转化与复购。"]
    out.append("")

    # ⑦ 明日关注事项：高优先项的处置闭环 + 趋势观察
    out += [f"## {SECTIONS[6]}", ""]
    watch = []
    if s.get("paid_not_shipped"):
        watch.append("复查今日未发货订单是否已全部出库。")
    if s.get("logistics_abnormal"):
        watch.append("跟踪异常物流包裹的最新签收状态。")
    if s.get("refund_abnormal"):
        watch.append("确认退款工单是否闭环，关注新增退款。")
    if s.get("amount_anomaly"):
        watch.append("核查金额异常订单的处理结果，确认无资损。")
    if s.get("low_stock"):
        watch.append("核对补货到货情况，更新可售库存。")
    watch.append("对比明日异常率变化，观察处置成效。")
    out += [f"- {w}" for w in watch]

    out += ["", data_quality_md(analysis)]
    return "\n".join(out)


def generate_ai_report(
    analysis: dict,
    cfg: Config | None = None,
    *,
    force_mock: bool = False,
) -> tuple[str, str]:
    """生成 AI 风格运营日报。

    返回 (markdown 文本, 实际使用的模式: "llm" | "mock")。
    - force_mock 或 provider 非真实/缺 Key → 走确定性 mock 渲染。
    - 否则调用真实模型（MiMo/Claude），失败自动回退 mock。
    """
    cfg = cfg or settings
    provider = cfg.llm_provider.lower()
    want_real = (not force_mock) and provider in {"mimo", "claude", "anthropic"} and bool(cfg.llm_api_key)
    if not want_real:
        return _mock_report(analysis), "mock"

    client = get_llm_client(cfg)
    if not (isinstance(client, AnthropicLLM) and client.available):
        return _mock_report(analysis), "mock"
    try:
        body = client.complete(_build_prompt(analysis), system=_SYSTEM_PROMPT)
        if not body.strip():
            return _mock_report(analysis), "mock"
        header = f"# 🤖 AI 运营日报 · {analysis['date']}\n\n> 由 {cfg.llm_model} 生成\n"
        # 数据质量块是确定性信息，统一由程序追加，不交给模型（避免幻觉）
        return f"{header}\n{body}\n\n{data_quality_md(analysis)}", "llm"
    except Exception as e:  # noqa: BLE001 —— 真实模型不可用时不阻断
        return _mock_report(analysis) + f"\n\n> _（实时生成失败，已回退 mock：{e}）_", "mock"
