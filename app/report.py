"""把分析结果渲染成 Markdown 运营日报。

风格对齐 AI_Agent_claude/agent/tools.py 的 _md_table / _build_markdown。
"""
from __future__ import annotations

from .config import Config, settings
from .llm import LLMClient, get_llm_client
from .schema import CANONICAL_LABELS


def _md_table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "_无_\n"
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows)
    return f"{head}\n{sep}\n{body}\n"


def _labels(canonicals: list[str]) -> str:
    """把 canonical 字段名转成中文标签，便于业务阅读。"""
    return "、".join(CANONICAL_LABELS.get(c, c) for c in canonicals) or "无"


def data_quality_md(analysis: dict) -> str:
    """统一的「数据质量提示」块（规则版 / AI 版共用，内容确定性、不交给 LLM）。

    展示：已识别字段 / 未识别字段 / 本次未参与分析的检测 / 关键字段是否缺失。
    """
    recognized = analysis.get("recognized_columns", [])
    unrecognized = analysis.get("unrecognized_columns", [])
    skipped = analysis.get("skipped_checks", [])
    key_missing = analysis.get("key_missing", [])
    lines = [
        "## 数据质量提示",
        "",
        f"- **已识别字段（{len(recognized)}）**：{_labels(recognized)}",
        f"- **未识别字段（{len(unrecognized)}）**：{'、'.join(unrecognized) or '无'}",
        "- **本次未参与分析**："
        + ("；".join(skipped) if skipped else "无，全部检测项均已执行"),
    ]
    if key_missing:
        lines.append(f"- **关键字段缺失**：⚠️ 是（缺 {_labels(key_missing)}，分析结果可能不完整）")
    else:
        lines.append("- **关键字段缺失**：否")
    return "\n".join(lines)


def build_report(
    analysis: dict,
    llm: LLMClient | None = None,
    cfg: Config | None = None,
) -> str:
    cfg = cfg or settings
    llm = llm or get_llm_client(cfg)
    titles = analysis["category_titles"]
    s = analysis["summary"]

    parts: list[str] = []
    parts.append(f"# 📊 电商运营日报 · {analysis['date']}")
    parts.append(f"> 生成时间：{analysis['generated_at']} ｜ 数据来源：上传订单文件\n")

    # 概览
    parts.append("## 一、数据概览")
    parts.append(_md_table(
        ["指标", "数值"],
        [
            ["订单总数", analysis["total_orders"]],
            ["异常订单数（去重）", analysis.get("anomaly_orders", analysis["anomaly_total"])],
            ["异常项数（含重复）", analysis["anomaly_total"]],
            *[[titles[k], v] for k, v in s.items()],
        ],
    ))

    # LLM 洞察
    parts.append("## 二、智能洞察与建议")
    parts.append(llm.summarize(analysis) + "\n")

    # 各类异常明细
    parts.append("## 三、异常明细")
    for key, title in titles.items():
        items = analysis["categories"].get(key, [])
        parts.append(f"### {title}（{len(items)}）")
        if not items:
            parts.append("_无_\n")
            continue
        shown = items[: cfg.report_max_rows]
        rows = [[it["order_id"], it["严重度"], it["原因"]] for it in shown]
        parts.append(_md_table(["订单号", "严重度", "原因"], rows))
        if len(items) > cfg.report_max_rows:
            parts.append(f"_……另有 {len(items) - cfg.report_max_rows} 条未展示_\n")

    # 数据质量（统一块）
    parts.append(data_quality_md(analysis))

    return "\n".join(parts)
