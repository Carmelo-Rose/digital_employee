"""通用业务域（General Domain）。

用于无法匹配任何已知业务域的表格，提供：
- 无字段映射（原始列名直通）
- 统计描述 + 缺失值 + 重复值 + 数值离群值检测
- 通用数据质量报告
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .base import BusinessDomain, CheckResult


class GeneralDomain(BusinessDomain):
    """通用域：对任意表格做基础数据质量扫描。"""

    @property
    def name(self) -> str:
        return "通用数据质量"

    @property
    def column_aliases(self) -> dict[str, list[str]]:
        # 不预设字段，所有列直接透传原始名
        return {}

    @property
    def key_fields(self) -> list[str]:
        return []

    @property
    def time_columns(self) -> set[str]:
        return set()

    @property
    def numeric_columns(self) -> set[str]:
        return set()

    # ── 异常检测 ─────────────────────────────────────────────────────────────

    def run_checks(self, df: Any, cfg: Any = None) -> list[CheckResult]:
        """对原始 df（保留原始列名）做通用质量扫描。"""
        results: list[CheckResult] = []

        # 1. 缺失值检测
        results.append(self._check_missing(df))

        # 2. 重复行检测
        results.append(self._check_duplicates(df))

        # 3. 数值列离群值检测（IQR）
        results.append(self._check_outliers(df))

        return results

    def _check_missing(self, df: pd.DataFrame) -> CheckResult:
        items: list[dict] = []
        for col in df.columns:
            null_count = int(df[col].isna().sum() + (df[col].astype(str).str.strip() == "").sum())
            if null_count > 0:
                pct = null_count / len(df) * 100 if len(df) > 0 else 0
                items.append({
                    "record_id": col,
                    "原因": f"缺失 {null_count} 行（{pct:.0f}%）",
                    "严重度": "严重" if pct >= 30 else "中",
                })
        return CheckResult(
            check_key="missing_values",
            title="缺失值",
            items=items,
        )

    def _check_duplicates(self, df: pd.DataFrame) -> CheckResult:
        dup_mask = df.duplicated()
        dup_count = int(dup_mask.sum())
        items: list[dict] = []
        if dup_count > 0:
            for idx in df[dup_mask].index[:10]:
                first_col = df.columns[0] if len(df.columns) > 0 else "行"
                items.append({
                    "record_id": f"行{idx + 2}",
                    "原因": f"{first_col}={df.loc[idx, first_col]!r} 与上行重复",
                    "严重度": "中",
                })
        return CheckResult(
            check_key="duplicates",
            title="重复行",
            items=items,
        )

    def _check_outliers(self, df: pd.DataFrame) -> CheckResult:
        items: list[dict] = []
        num_cols = df.select_dtypes(include="number").columns
        for col in num_cols:
            s = df[col].dropna()
            if len(s) < 4:
                continue
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = df[(df[col] < lower) | (df[col] > upper)]
            for idx, row in outliers.iterrows():
                items.append({
                    "record_id": f"行{idx + 2}",
                    "原因": f"{col}={row[col]:.4g}（正常范围 {lower:.4g}~{upper:.4g}）",
                    "严重度": "中",
                })
        return CheckResult(
            check_key="outliers",
            title="数值离群值",
            items=items,
        )

    # ── build_analysis_dict 覆盖：直接用原始 df 列名 ─────────────────────────

    def build_analysis_dict(self, results: list[CheckResult], df_len: int, now: Any) -> dict:
        base = super().build_analysis_dict(results, df_len, now)
        base["domain"] = "general"
        return base

    # ── 报告生成 ─────────────────────────────────────────────────────────────

    def get_system_prompt(self) -> str:
        return (
            "你是数据质量分析师，请根据以下扫描结果生成简洁的数据质量报告（中文，Markdown 格式）。"
            "报告包含：总体评价、各类问题列表（缺失值/重复行/离群值）、优先处理建议。"
            "不要猜测业务含义，只描述数据本身的问题。"
        )

    def get_report_sections(self) -> list[str]:
        return ["总体评价", "缺失值明细", "重复行明细", "数值离群值明细", "处理建议"]

    def build_mock_report(self, analysis: dict) -> str:
        date = analysis.get("date", datetime.now().strftime("%Y-%m-%d"))
        total = analysis.get("total_orders", 0)
        cats = analysis.get("categories", {})
        titles = analysis.get("category_titles", {})

        missing = cats.get("missing_values", [])
        dups = cats.get("duplicates", [])
        outliers = cats.get("outliers", [])

        problem_count = len(missing) + len(dups) + len(outliers)
        health = "存在问题，建议清洗后再分析" if problem_count > 0 else "数据质量良好"

        lines = [
            f"# 数据质量扫描报告 · {date}",
            "",
            f"> 共扫描 **{total}** 行数据，发现 **{problem_count}** 项问题。{health}",
            "",
            "---",
            "",
        ]

        # 缺失值
        lines += ["## 缺失值", ""]
        if missing:
            for it in missing:
                lines.append(f"- **{it['record_id']}**：{it['原因']}（{it['严重度']}）")
        else:
            lines.append("无缺失值 ✓")
        lines.append("")

        # 重复行
        lines += ["## 重复行", ""]
        if dups:
            lines.append(f"共 {len(dups)} 行重复（仅展示前 10 条）：")
            for it in dups[:10]:
                lines.append(f"- {it['record_id']}：{it['原因']}")
        else:
            lines.append("无重复行 ✓")
        lines.append("")

        # 离群值
        lines += ["## 数值离群值（IQR × 1.5）", ""]
        if outliers:
            lines.append(f"共 {len(outliers)} 处离群值：")
            for it in outliers[:15]:
                lines.append(f"- {it['record_id']}：{it['原因']}")
        else:
            lines.append("无数值离群值 ✓")
        lines.append("")

        # 建议
        lines += ["## 处理建议", ""]
        if not missing and not dups and not outliers:
            lines.append("数据质量良好，可直接用于分析。")
        else:
            if missing:
                severe_missing = [m for m in missing if m["严重度"] == "严重"]
                if severe_missing:
                    cols = "、".join(m["record_id"] for m in severe_missing)
                    lines.append(f"1. **优先补充**缺失率 ≥30% 的字段：{cols}")
                else:
                    lines.append("1. 评估缺失值是否影响分析目标，酌情补充或剔除。")
            if dups:
                lines.append(f"{'2' if missing else '1'}. 去重处理 {len(dups)} 条重复行后再分析。")
            if outliers:
                lines.append(f"- 核实 {len(outliers)} 处离群值是否为录入错误或真实极端值。")
        lines.append("")
        lines += [
            "---",
            "",
            "> **注**：本报告基于通用数据质量规则，未识别具体业务域。"
            "如需精准异常检测，请确保上传的表格为电商订单表或 HR 人事表。",
        ]
        return "\n".join(lines)
