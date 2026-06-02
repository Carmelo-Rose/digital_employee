"""电商运营业务域。

聚合了原 schema.py / analyzer.py / llm_reporter.py 里的所有电商专属逻辑：
- 字段定义与别名映射
- 六类异常检测规则
- LLM system prompt 与报告板块
- mock 日报渲染

其他业务域照此模式实现 BusinessDomain，不需要修改任何节点或图编排代码。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .base import BusinessDomain, CheckResult


class EcommerceDomain(BusinessDomain):
    """电商运营：订单异常检测 + AI 运营日报。"""

    # ── 字段定义 ─────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "电商运营"

    @property
    def column_aliases(self) -> dict[str, list[str]]:
        return {
            "order_id":             ["订单号", "订单编号", "订单id", "order_id", "order_no"],
            "store_name":           ["店铺名称", "店铺", "门店", "store_name", "shop_name"],
            "pay_status":           ["支付状态", "付款状态", "payment_status", "pay_status"],
            "pay_time":             ["支付时间", "付款时间", "pay_time", "payment_time"],
            "ship_status":          ["发货状态", "shipping_status", "ship_status"],
            "ship_time":            ["发货时间", "ship_time"],
            "logistics_status":     ["物流状态", "快递状态", "logistics_status"],
            "logistics_update_time":["物流更新时间", "最近物流时间", "logistics_update_time"],
            "refund_status":        ["退款状态", "refund_status"],
            "refund_apply_time":    ["退款申请时间", "refund_apply_time"],
            "sku":                  ["商品SKU", "sku", "货号"],
            "product_name":         ["商品名称", "宝贝名称", "product_name"],
            "quantity":             ["购买数量", "数量", "quantity", "qty"],
            "stock":                ["库存", "库存数量", "可用库存", "stock", "stock_qty"],
            "amount":               ["订单金额", "实付金额", "amount", "total_amount"],
            "cs_note":              ["客服备注", "备注", "留言", "cs_note", "customer_note", "remark"],
        }

    @property
    def key_fields(self) -> list[str]:
        return ["order_id", "pay_status", "ship_status"]

    @property
    def time_columns(self) -> set[str]:
        return {"pay_time", "ship_time", "logistics_update_time", "refund_apply_time"}

    @property
    def numeric_columns(self) -> set[str]:
        return {"quantity", "stock", "amount"}

    # ── 异常检测 ─────────────────────────────────────────────────────────────

    def run_checks(self, df: pd.DataFrame, cfg: Any = None) -> list[CheckResult]:
        from ..config import settings
        cfg = cfg or settings
        now = datetime.now()
        return [
            self._check_paid_not_shipped(df, cfg, now),
            self._check_logistics(df, cfg, now),
            self._check_refund(df, cfg, now),
            self._check_stock(df, cfg, now),
            self._check_cs_keyword(df, cfg, now),
            self._check_amount(df, cfg, now),
        ]

    # ── 检测规则（私有） ──────────────────────────────────────────────────────

    @staticmethod
    def _has(df: pd.DataFrame, *cols: str) -> bool:
        return all(c in df.columns for c in cols)

    @staticmethod
    def _row_id(row: pd.Series, idx: int) -> str:
        val = str(row.get("order_id", "")).strip()
        return val if val else f"第{idx + 1}行"

    def _check_paid_not_shipped(self, df: pd.DataFrame, cfg: Any, now: datetime) -> CheckResult:
        if not self._has(df, "pay_status", "ship_status"):
            return CheckResult("paid_not_shipped", "已付款未发货", [], "缺少 支付状态/发货状态 列")
        items: list[dict] = []
        has_pay_time = "pay_time" in df.columns
        for idx, row in df.iterrows():
            if "已付款" not in str(row["pay_status"]):
                continue
            ship = str(row["ship_status"])
            if "未发货" not in ship and "部分发货" not in ship:
                continue
            severity, hours = "中", None
            if has_pay_time and pd.notna(row["pay_time"]):
                hours = round((now - row["pay_time"]).total_seconds() / 3600, 1)
                if hours > cfg.pay_no_ship_hours:
                    severity = "严重"
            items.append({
                "record_id": self._row_id(row, idx),
                "原因": f"已付款但{ship}" + (f"，付款已 {hours} 小时" if hours is not None else ""),
                "严重度": severity,
                "关键值": ship,
            })
        return CheckResult("paid_not_shipped", "已付款未发货", items)

    def _check_logistics(self, df: pd.DataFrame, cfg: Any, now: datetime) -> CheckResult:
        if not self._has(df, "logistics_status"):
            return CheckResult("logistics_abnormal", "物流异常/超时", [], "缺少 物流状态 列")
        bad_states = ("物流异常", "退回", "超时", "异常")
        items: list[dict] = []
        has_update = "logistics_update_time" in df.columns
        has_ship = "ship_status" in df.columns
        for idx, row in df.iterrows():
            status = str(row["logistics_status"])
            reason = severity = None
            if any(b in status for b in bad_states):
                reason, severity = f"物流状态：{status}", "严重"
            elif has_update and pd.notna(row["logistics_update_time"]):
                shipped = (not has_ship) or ("已发货" in str(row["ship_status"]))
                stale_days = (now - row["logistics_update_time"]).days
                if shipped and stale_days > cfg.logistics_stale_days:
                    reason, severity = f"物流 {stale_days} 天无更新", "中"
            if reason:
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": reason,
                    "严重度": severity,
                    "关键值": status,
                })
        return CheckResult("logistics_abnormal", "物流异常/超时", items)

    def _check_refund(self, df: pd.DataFrame, cfg: Any, now: datetime) -> CheckResult:
        if not self._has(df, "refund_status"):
            return CheckResult("refund_abnormal", "退款状态异常", [], "缺少 退款状态 列")
        items: list[dict] = []
        has_apply = "refund_apply_time" in df.columns
        for idx, row in df.iterrows():
            status = str(row["refund_status"])
            reason = severity = None
            if "退款失败" in status or "异常" in status:
                reason, severity = f"退款状态：{status}", "严重"
            elif "退款中" in status and has_apply and pd.notna(row["refund_apply_time"]):
                days = (now - row["refund_apply_time"]).days
                if days > cfg.refund_pending_days:
                    reason, severity = f"退款中已 {days} 天未完成", "中"
            if reason:
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": reason,
                    "严重度": severity,
                    "关键值": status,
                })
        return CheckResult("refund_abnormal", "退款状态异常", items)

    def _check_stock(self, df: pd.DataFrame, cfg: Any, now: datetime) -> CheckResult:
        if not self._has(df, "stock"):
            return CheckResult("low_stock", "库存不足", [], "缺少 库存 列")
        items: list[dict] = []
        has_qty = "quantity" in df.columns
        for idx, row in df.iterrows():
            stock = row["stock"]
            if pd.isna(stock):
                continue
            stock = float(stock)
            qty = float(row["quantity"]) if has_qty and pd.notna(row.get("quantity")) else None
            reason = severity = None
            if stock <= 0:
                reason, severity = f"库存为 {int(stock)}", "严重"
            elif qty is not None and stock < qty:
                reason, severity = f"库存 {int(stock)} < 本单数量 {int(qty)}", "严重"
            elif stock <= cfg.stock_low_threshold:
                reason, severity = f"库存偏低（{int(stock)} ≤ {cfg.stock_low_threshold}）", "中"
            if reason:
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": reason + (f"，商品：{row['product_name']}" if "product_name" in df.columns else ""),
                    "严重度": severity,
                    "关键值": int(stock),
                })
        return CheckResult("low_stock", "库存不足", items)

    def _check_cs_keyword(self, df: pd.DataFrame, cfg: Any, now: datetime) -> CheckResult:
        if not self._has(df, "cs_note"):
            return CheckResult("cs_keyword", "客服备注预警", [], "缺少 客服备注 列")
        items: list[dict] = []
        for idx, row in df.iterrows():
            note = str(row["cs_note"])
            if not note:
                continue
            hits = sorted({label for kw, label in cfg.cs_keywords.items() if kw in note})
            if hits:
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": f"命中关键词：{'、'.join(hits)}",
                    "严重度": "严重" if "投诉" in hits or "质量问题" in hits else "中",
                    "关键值": note[:40],
                })
        return CheckResult("cs_keyword", "客服备注预警", items)

    def _check_amount(self, df: pd.DataFrame, cfg: Any, now: datetime) -> CheckResult:
        if not self._has(df, "amount"):
            return CheckResult("amount_anomaly", "订单金额异常", [], "缺少 订单金额 列")
        items: list[dict] = []
        for idx, row in df.iterrows():
            amt = row["amount"]
            if pd.isna(amt):
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": "订单金额缺失/无法解析",
                    "严重度": "中",
                    "关键值": "",
                })
            elif float(amt) <= 0:
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": f"订单金额异常：{amt}",
                    "严重度": "严重",
                    "关键值": float(amt),
                })
        return CheckResult("amount_anomaly", "订单金额异常", items)

    # ── 报告生成 ─────────────────────────────────────────────────────────────

    def get_system_prompt(self) -> str:
        sections = "、".join(self.get_report_sections())
        return (
            "你是一名经验丰富的电商运营负责人，每天给团队写运营日报。"
            "我会给你今天订单的结构化异常分析数据，请你写成一份自然、专业、有判断力的中文运营日报，"
            "语气像真人运营负责人在跟团队交代工作，不要像机器罗列统计。"
            f"必须且只能包含以下 7 个二级标题板块（顺序一致，用 Markdown 的 ## ）：{sections}。"
            "核心要求（这是日报的价值所在）："
            "1) 明确指出异常主要集中在哪个环节（发货 / 物流 / 退款 / 库存 / 客诉）；"
            "2) 判断哪类问题优先级最高、为什么；"
            "3) 区分『今天必须处理』和『可以次日观察』的事项，分别放进对应板块；"
            "4) 点名具体订单号，「AI 运营建议」给可执行动作并指明责任方（仓储/客服/采购等）。"
            "约束：不要堆砌原始表格；不要编造数据里没有的数字；"
            "对于数据中标注『未识别 / 未参与分析』的字段，不要凭空给出该维度的风险结论。"
            "不要写一级大标题（# 开头），直接从第一个 ## 板块开始输出。"
        )

    def get_report_sections(self) -> list[str]:
        return [
            "今日订单概况",
            "重点异常问题",
            "需要优先处理的订单",
            "商品 / 库存风险",
            "客服备注风险",
            "AI 运营建议",
            "明日关注事项",
        ]

    # ── mock 报告渲染 ─────────────────────────────────────────────────────────

    # 每类异常的业务元数据：归属环节、优先级、判断文案
    _CAT_META: dict[str, dict[str, str]] = {
        "paid_not_shipped": {"env": "履约", "prio": "高", "why": "付款未发货易触发超时赔付与差评"},
        "logistics_abnormal": {"env": "履约", "prio": "高", "why": "物流异常/超时直接影响签收体验"},
        "refund_abnormal":  {"env": "售后", "prio": "高", "why": "退款失败/异常涉及资金安全与平台介入"},
        "amount_anomaly":   {"env": "交易", "prio": "高", "why": "金额异常可能是错单、改价或营销漏洞"},
        "cs_keyword":       {"env": "口碑", "prio": "高", "why": "投诉/质量类备注须当天回访安抚"},
        "low_stock":        {"env": "商品", "prio": "中", "why": "库存不足影响后续履约，需补货跟进"},
    }

    def build_mock_report(self, analysis: dict) -> str:
        from ..report import data_quality_md
        sections = self.get_report_sections()
        titles = analysis["category_titles"]
        cats = analysis["categories"]
        s = analysis["summary"]
        total = analysis["total_orders"]
        anomaly = analysis.get("anomaly_orders", analysis["anomaly_total"])
        rate = (anomaly / total * 100) if total else 0
        health = "良好" if rate < 20 else ("需关注" if rate < 50 else "风险偏高")

        def lst(key: str, n: int = 8) -> list[str]:
            return [
                f"- `{it.get('record_id') or it.get('order_id', '')}`：{it['原因']}"
                for it in cats.get(key, [])[:n]
            ]

        def severe_items() -> list[dict]:
            seen: dict[str, dict] = {}
            for key, items in cats.items():
                for it in items:
                    if it.get("严重度") == "严重":
                        oid = it.get("record_id") or it.get("order_id", "")
                        if oid not in seen:
                            seen[oid] = {"record_id": oid, "类别": titles.get(key, key), "原因": it["原因"]}
            return list(seen.values())

        out: list[str] = [f"# AI 运营日报 · {analysis['date']}", ""]

        # ① 今日订单概况
        out += [f"## {sections[0]}", ""]
        out.append(
            f"今天共处理 **{total}** 笔订单，其中 **{anomaly}** 笔存在异常，"
            f"异常率约 **{rate:.1f}%**，整体运营健康度 **{health}**。"
        )
        env_sum: dict[str, int] = {}
        for k, v in s.items():
            if v > 0 and k in self._CAT_META:
                env = self._CAT_META[k]["env"]
                env_sum[env] = env_sum.get(env, 0) + v
        if env_sum:
            ranked = sorted(env_sum.items(), key=lambda kv: -kv[1])
            top_env, top_n = ranked[0]
            rest = "、".join(f"{e}（{n} 项）" for e, n in ranked[1:3])
            line = f"从环节看，问题主要集中在 **{top_env}环节**（{top_n} 项）"
            line += f"，其次是 {rest}" if rest else ""
            out.append(line + "，应作为今天运营的主战场。")
        else:
            out.append("今日未发现明显异常，运营状态平稳，按常规节奏运营即可。")
        out.append("")

        # ② 重点异常问题
        out += [f"## {sections[1]}", ""]
        nonzero = [(k, v) for k, v in s.items() if v > 0]
        if not nonzero:
            out += ["今日无突出异常问题，保持常规运营节奏即可。", ""]
        else:
            high = sorted(
                [kv for kv in nonzero if self._CAT_META.get(kv[0], {}).get("prio") == "高"],
                key=lambda kv: -kv[1],
            )
            mid = sorted(
                [kv for kv in nonzero if self._CAT_META.get(kv[0], {}).get("prio") != "高"],
                key=lambda kv: -kv[1],
            )
            if high:
                out.append("**🔴 高优先（今天必须处理）**")
                out += [f"- **{titles[k]}**（{v} 单）：{self._CAT_META[k]['why']}。" for k, v in high]
            if mid:
                out.append("")
                out.append("**🟡 中优先（可次日跟进观察）**")
                out += [
                    f"- **{titles[k]}**（{v} 单）：{self._CAT_META.get(k, {}).get('why', '持续观察')}。"
                    for k, v in mid
                ]
            out.append("")

        # ③ 需要优先处理的订单
        out += [f"## {sections[2]}", ""]
        severe = severe_items()
        if severe:
            out.append(
                f"按「履约 > 售后 / 口碑 > 商品」的优先级，今天先清以下 **{len(severe)}** 笔严重级订单："
            )
            out += [f"- `{x['record_id']}`（{x['类别']}）：{x['原因']}" for x in severe[:12]]
            if len(severe) > 12:
                out.append(f"- …另有 {len(severe) - 12} 笔严重订单")
        else:
            out.append("当前无严重级订单，按常规节奏处理异常即可。")
        out.append("")

        skipped_keys = set(analysis.get("skipped_keys", []))

        # ④ 商品/库存风险
        out += [f"## {sections[3]}", ""]
        if "low_stock" in skipped_keys:
            out.append("未识别库存字段，本次未进行库存风险分析。")
        else:
            stock_items = lst("low_stock")
            out += (["库存存在以下风险，需补货或下架防超卖："] + stock_items) if stock_items else ["商品库存暂无明显风险。"]
        out.append("")

        # ⑤ 客服备注风险
        out += [f"## {sections[4]}", ""]
        if "cs_keyword" in skipped_keys:
            out.append("未识别客服备注字段，本次未进行客服备注风险分析。")
        else:
            cs_items = lst("cs_keyword")
            out += (["客服备注命中风险关键词，需逐条回访："] + cs_items) if cs_items else ["客服备注未见风险关键词。"]
        out.append("")

        # ⑥ AI 运营建议
        out += [f"## {sections[5]}", ""]
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

        # ⑦ 明日关注事项
        out += [f"## {sections[6]}", ""]
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
