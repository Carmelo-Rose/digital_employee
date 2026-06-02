"""HR 人事业务域。

检测规则：
- 试用期超期未转正（入职满 N 天、合同到期日已过、状态仍是试用期）
- 合同到期未续签（到期日 ≤ today + 提前预警天数）
- 离职中但工作未交接
- 合同/转正材料未提交
- 员工数据缺失（姓名/部门/岗位为空）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .base import BusinessDomain, CheckResult


class HRDomain(BusinessDomain):
    """HR 人事：员工状态异常检测 + 人事日报。"""

    # ── 字段定义 ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "HR 人事"

    @property
    def column_aliases(self) -> dict[str, list[str]]:
        return {
            "emp_id":           ["员工编号", "工号", "员工id", "emp_id", "employee_id", "staff_no", "staff_id"],
            "emp_name":         ["姓名", "员工姓名", "name", "emp_name", "employee_name", "staff_name"],
            "department":       ["部门", "所属部门", "department", "dept", "team"],
            "position":         ["岗位", "职位", "职务", "position", "job_title", "title", "role"],
            "hire_date":        ["入职日期", "入职时间", "入职日", "hire_date", "start_date", "onboard_date"],
            "contract_end":     ["合同到期日", "合同截止日", "合同到期时间", "contract_end", "contract_expire", "contract_end_date"],
            "emp_status":       ["员工状态", "在职状态", "状态", "emp_status", "status", "employment_status"],
            "probation_result": ["转正考核材料", "转正材料", "考核材料", "转正状态", "probation_result", "probation_status"],
            "remark":           ["备注", "说明", "remark", "note", "comment"],
        }

    @property
    def key_fields(self) -> list[str]:
        return ["emp_id", "emp_name", "emp_status"]

    @property
    def time_columns(self) -> set[str]:
        return {"hire_date", "contract_end"}

    @property
    def numeric_columns(self) -> set[str]:
        return set()

    @property
    def canonical_labels(self) -> dict[str, str]:
        return {
            "emp_id":           "员工编号",
            "emp_name":         "姓名",
            "department":       "部门",
            "position":         "岗位",
            "hire_date":        "入职日期",
            "contract_end":     "合同到期日",
            "emp_status":       "员工状态",
            "probation_result": "转正考核材料",
            "remark":           "备注",
        }

    # ── 异常检测 ──────────────────────────────────────────────────────────────

    def run_checks(self, df: pd.DataFrame, cfg: Any = None) -> list[CheckResult]:
        now = datetime.now()
        return [
            self._check_probation_overdue(df, now),
            self._check_contract_expiring(df, now),
            self._check_resignation_handover(df, now),
            self._check_missing_docs(df, now),
            self._check_data_missing(df, now),
        ]

    # ── 检测规则（私有）──────────────────────────────────────────────────────

    @staticmethod
    def _has(df: pd.DataFrame, *cols: str) -> bool:
        return all(c in df.columns for c in cols)

    @staticmethod
    def _row_id(row: pd.Series, idx: int) -> str:
        for col in ("emp_name", "emp_id"):
            val = str(row.get(col, "")).strip()
            if val and val != "nan":
                return val
        return f"第{idx + 1}行"

    def _check_probation_overdue(self, df: pd.DataFrame, now: datetime) -> CheckResult:
        """试用期已过（入职满 90 天 或 合同到期已过）但状态未转正。"""
        if not self._has(df, "emp_status"):
            return CheckResult("probation_overdue", "试用期超期未转正", [], "缺少 员工状态 列")

        items: list[dict] = []
        has_hire = "hire_date" in df.columns
        has_end = "contract_end" in df.columns

        for idx, row in df.iterrows():
            status = str(row["emp_status"])
            if "试用" not in status:
                continue

            reason = severity = None

            # 合同到期日已过 → 严重
            if has_end and pd.notna(row["contract_end"]):
                days_over = (now - row["contract_end"]).days
                if days_over > 0:
                    reason = f"合同到期日已过 {days_over} 天，仍处于试用期"
                    severity = "严重"

            # 入职满 90 天仍试用 → 中
            if reason is None and has_hire and pd.notna(row["hire_date"]):
                days_in = (now - row["hire_date"]).days
                if days_in >= 90:
                    reason = f"入职已 {days_in} 天，仍在试用期未处理"
                    severity = "中"

            if reason:
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": reason,
                    "严重度": severity,
                    "关键值": status,
                })
        return CheckResult("probation_overdue", "试用期超期未转正", items)

    def _check_contract_expiring(self, df: pd.DataFrame, now: datetime) -> CheckResult:
        """合同即将到期（30 天内）或已到期未续签。"""
        if not self._has(df, "contract_end"):
            return CheckResult("contract_expiring", "合同到期未续签", [], "缺少 合同到期日 列")

        items: list[dict] = []
        for idx, row in df.iterrows():
            if pd.isna(row["contract_end"]):
                continue
            days_left = (row["contract_end"] - now).days
            status = str(row.get("emp_status", ""))
            # 跳过离职中（离职交接那条单独检测）
            if "离职" in status:
                continue
            reason = severity = None
            if days_left < 0:
                reason = f"合同已于 {abs(days_left)} 天前到期，未续签"
                severity = "严重"
            elif days_left <= 7:
                reason = f"合同 {days_left} 天后到期（即将到期），需紧急跟进"
                severity = "严重"
            elif days_left <= 30:
                reason = f"合同 {days_left} 天后到期，需提前续签"
                severity = "中"
            if reason:
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": reason,
                    "严重度": severity,
                    "关键值": str(row["contract_end"])[:10],
                })
        return CheckResult("contract_expiring", "合同到期未续签", items)

    def _check_resignation_handover(self, df: pd.DataFrame, now: datetime) -> CheckResult:
        """离职中但工作交接未完成（备注含'未交接'/'未完成'等关键词）。"""
        if not self._has(df, "emp_status"):
            return CheckResult("resignation_handover", "离职交接未完成", [], "缺少 员工状态 列")

        items: list[dict] = []
        has_remark = "remark" in df.columns

        for idx, row in df.iterrows():
            status = str(row["emp_status"])
            if "离职" not in status:
                continue
            note = str(row.get("remark", "")) if has_remark else ""
            bad_keywords = ("未交接", "未完成", "未处理", "待交接")
            reason = severity = None
            if any(kw in note for kw in bad_keywords):
                reason = f"离职中，备注：{note[:40]}"
                severity = "严重"
            elif not note or note in ("nan", ""):
                reason = "离职中，交接情况未记录"
                severity = "中"
            if reason:
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": reason,
                    "严重度": severity,
                    "关键值": status,
                })
        return CheckResult("resignation_handover", "离职交接未完成", items)

    def _check_missing_docs(self, df: pd.DataFrame, now: datetime) -> CheckResult:
        """转正/合同材料未提交。"""
        if not self._has(df, "probation_result"):
            return CheckResult("missing_docs", "材料未提交", [], "缺少 转正考核材料 列")

        items: list[dict] = []
        bad_vals = ("未提交", "未签署", "未签", "")

        for idx, row in df.iterrows():
            status = str(row.get("emp_status", ""))
            # 只检查在职/试用期员工
            if "离职" in status:
                continue
            doc = str(row["probation_result"]).strip()
            if doc in ("nan", "None"):
                doc = ""
            if doc in bad_vals:
                severity = "严重" if "试用" in status else "中"
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": f"转正/合同材料未提交（当前状态：{status}）",
                    "严重度": severity,
                    "关键值": doc or "空",
                })
        return CheckResult("missing_docs", "材料未提交", items)

    def _check_data_missing(self, df: pd.DataFrame, now: datetime) -> CheckResult:
        """员工基础信息缺失（姓名/部门/岗位为空）。"""
        items: list[dict] = []
        check_cols = [c for c in ("emp_name", "department", "position") if c in df.columns]
        if not check_cols:
            return CheckResult("data_missing", "基础信息缺失", [], "缺少 姓名/部门/岗位 列")

        labels = {"emp_name": "姓名", "department": "部门", "position": "岗位"}
        for idx, row in df.iterrows():
            missing = [
                labels[c] for c in check_cols
                if str(row.get(c, "")).strip() in ("", "nan", "None")
            ]
            if missing:
                items.append({
                    "record_id": self._row_id(row, idx),
                    "原因": f"基础字段缺失：{'、'.join(missing)}",
                    "严重度": "中",
                    "关键值": "缺失",
                })
        return CheckResult("data_missing", "基础信息缺失", items)

    # ── 报告生成 ──────────────────────────────────────────────────────────────

    def get_system_prompt(self) -> str:
        sections = "、".join(self.get_report_sections())
        return (
            "你是一名经验丰富的 HR 负责人，每天给管理层写人事日报。"
            "我会给你今天员工数据的结构化异常分析，请写成一份自然、专业的中文人事日报，"
            "语气像真人 HR 在跟管理层汇报，不要机器罗列统计。"
            f"必须且只能包含以下 6 个二级标题板块（顺序一致，用 ## ）：{sections}。"
            "核心要求："
            "1) 明确指出最紧迫的人事风险（试用期/合同/离职交接哪类最集中）；"
            "2) 区分『本周必须处理』和『可下周跟进』的事项；"
            "3) 点名具体员工姓名，给出可执行的跟进动作并指明责任方（HR/部门主管/法务等）；"
            "4) 合同类问题重点提示法务/用工风险。"
            "约束：不要堆砌原始表格；不要编造数据里没有的数字；"
            "对于数据中标注未识别的字段，不要给出该维度的结论。"
            "不要写一级大标题（# 开头），直接从第一个 ## 板块开始输出。"
        )

    def get_report_sections(self) -> list[str]:
        return [
            "今日人员概况",
            "重点人事风险",
            "需立即处理的事项",
            "合同 / 材料跟进",
            "HR 行动建议",
            "下周关注事项",
        ]

    # ── mock 报告渲染 ─────────────────────────────────────────────────────────

    _CAT_META: dict[str, dict[str, str]] = {
        "probation_overdue":    {"prio": "高", "why": "试用期超期未转正存在用工合规风险"},
        "contract_expiring":    {"prio": "高", "why": "合同到期未续签面临劳动关系中断风险"},
        "resignation_handover": {"prio": "高", "why": "离职交接未完成影响业务连续性与数据安全"},
        "missing_docs":         {"prio": "中", "why": "材料缺失影响考核归档与法律凭证完整性"},
        "data_missing":         {"prio": "中", "why": "基础信息缺失影响人员管理准确性"},
    }

    def build_mock_report(self, analysis: dict) -> str:
        from ..report import data_quality_md
        sections = self.get_report_sections()
        titles = analysis["category_titles"]
        cats = analysis["categories"]
        s = analysis["summary"]
        total = analysis["total_orders"]       # 复用字段：此处为员工总数
        anomaly = analysis.get("anomaly_orders", analysis["anomaly_total"])
        rate = (anomaly / total * 100) if total else 0
        health = "良好" if rate < 20 else ("需关注" if rate < 50 else "风险偏高")

        def lst(key: str, n: int = 8) -> list[str]:
            return [
                f"- **{it.get('record_id', '')}**：{it['原因']}"
                for it in cats.get(key, [])[:n]
            ]

        def severe_items() -> list[dict]:
            seen: dict[str, dict] = {}
            for key, items in cats.items():
                for it in items:
                    if it.get("严重度") == "严重":
                        rid = it.get("record_id", "")
                        if rid not in seen:
                            seen[rid] = {"record_id": rid, "类别": titles.get(key, key), "原因": it["原因"]}
            return list(seen.values())

        out: list[str] = [f"# AI 人事日报 · {analysis['date']}", ""]

        # ① 今日人员概况
        out += [f"## {sections[0]}", ""]
        out.append(
            f"今日共扫描 **{total}** 名员工档案，发现 **{anomaly}** 名存在人事异常，"
            f"异常率约 **{rate:.1f}%**，整体人事健康度 **{health}**。"
        )
        nonzero = {k: v for k, v in s.items() if v > 0}
        if nonzero:
            top_k = max(nonzero, key=lambda k: nonzero[k])
            out.append(f"最突出问题为「{titles.get(top_k, top_k)}」（{nonzero[top_k]} 人），需重点跟进。")
        else:
            out.append("今日未发现明显人事异常，档案状态良好。")
        out.append("")

        # ② 重点人事风险
        out += [f"## {sections[1]}", ""]
        if not nonzero:
            out += ["暂无突出人事风险。", ""]
        else:
            high = [(k, v) for k, v in nonzero.items() if self._CAT_META.get(k, {}).get("prio") == "高"]
            mid  = [(k, v) for k, v in nonzero.items() if self._CAT_META.get(k, {}).get("prio") != "高"]
            if high:
                out.append("**🔴 高优先（本周必须处理）**")
                out += [f"- **{titles[k]}**（{v} 人）：{self._CAT_META[k]['why']}。" for k, v in sorted(high, key=lambda x: -x[1])]
            if mid:
                out.append("")
                out.append("**🟡 中优先（可下周跟进）**")
                out += [f"- **{titles[k]}**（{v} 人）：{self._CAT_META.get(k, {}).get('why', '持续观察')}。" for k, v in sorted(mid, key=lambda x: -x[1])]
            out.append("")

        # ③ 需立即处理的事项
        out += [f"## {sections[2]}", ""]
        severe = severe_items()
        if severe:
            out.append(f"以下 **{len(severe)}** 名员工存在严重级问题，需本周内处理：")
            out += [f"- **{x['record_id']}**（{x['类别']}）：{x['原因']}" for x in severe[:12]]
            if len(severe) > 12:
                out.append(f"- …另有 {len(severe) - 12} 人需跟进")
        else:
            out.append("暂无严重级人事问题，按常规节奏跟进即可。")
        out.append("")

        skipped_keys = set(analysis.get("skipped_keys", []))

        # ④ 合同 / 材料跟进
        out += [f"## {sections[3]}", ""]
        contract_items = lst("contract_expiring")
        doc_items = lst("missing_docs")
        if "contract_expiring" in skipped_keys:
            out.append("未识别合同到期日字段，本次未进行合同风险分析。")
        elif contract_items:
            out += ["以下员工合同即将到期或已到期，需法务/HR 跟进续签："] + contract_items
        else:
            out.append("暂无合同到期风险。")
        out.append("")
        if "missing_docs" in skipped_keys:
            out.append("未识别转正材料字段，本次未进行材料核查。")
        elif doc_items:
            out += ["以下员工材料未提交，需部门主管督促："] + doc_items
        else:
            out.append("材料归档情况正常。")
        out.append("")

        # ⑤ HR 行动建议
        out += [f"## {sections[4]}", ""]
        advice = []
        if s.get("probation_overdue"):
            advice.append("**HR + 部门主管**：本周内完成试用期超期员工的转正评估或谈话，避免合规风险。")
        if s.get("contract_expiring"):
            advice.append("**HR + 法务**：推动合同即将到期员工的续签流程，已到期的优先处理，防止用工关系中断。")
        if s.get("resignation_handover"):
            advice.append("**部门主管**：督促离职员工完成工作交接，更新系统账号权限，确保业务连续。")
        if s.get("missing_docs"):
            advice.append("**HR**：催收缺失的转正/合同材料，确保档案完整，为考核与仲裁留存凭证。")
        if s.get("data_missing"):
            advice.append("**HR 数据专员**：补全基础信息缺失的员工档案，确保人员管理数据准确。")
        out += [f"{i}. {a}" for i, a in enumerate(advice, 1)] if advice else ["1. 保持当前人事管理节奏，持续监控档案状态。"]
        out.append("")

        # ⑥ 下周关注事项
        out += [f"## {sections[5]}", ""]
        watch = []
        if s.get("probation_overdue"):
            watch.append("复查试用期超期员工的转正/终止处理结果。")
        if s.get("contract_expiring"):
            watch.append("确认合同续签进度，关注新增到期人员。")
        if s.get("resignation_handover"):
            watch.append("跟踪离职交接完成情况，确认权限收回。")
        if s.get("missing_docs"):
            watch.append("核实材料归档完整性，更新档案状态。")
        watch.append("扫描下周合同到期与新入职员工，提前预警。")
        out += [f"- {w}" for w in watch]

        out += ["", data_quality_md(analysis)]
        return "\n".join(out)
