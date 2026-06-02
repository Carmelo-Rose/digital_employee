"""业务域抽象基类。

每个业务场景（电商、HR、财务…）继承 BusinessDomain 并实现全部抽象属性/方法，
即可接入数字员工工作流，无需修改任何节点或 LangGraph 编排代码。

新增业务步骤：
  1. 在 app/domains/ 下新建 my_domain.py，继承 BusinessDomain。
  2. 在 app/domains/__init__.py 的 DOMAIN_REGISTRY 里注册。
  3. 启动时传 domain_name="my_domain" 即可。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    """单项异常检测的结构化输出。"""
    check_key: str          # 唯一标识，如 "paid_not_shipped"
    title: str              # 中文标题，如 "已付款未发货"
    items: list[dict]       # 每条异常记录，必须包含：
                            #   "record_id" — 行级唯一标识（可以是 order_id/employee_id 等，统一用此键）
                            #   "原因"     — 人类可读的异常说明
                            #   "严重度"   — "严重" | "中" | "低"
    skip_reason: str | None = None  # 非 None 时表示该检测因缺字段被跳过


@dataclass
class DomainConfig:
    """业务域可调阈值，由 app/config.py 的 Config 注入（或使用默认值）。"""
    thresholds: dict[str, Any] = field(default_factory=dict)


class BusinessDomain(ABC):
    """所有业务域的公共接口契约。"""

    # ── 字段定义（子类用类变量覆盖）────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """业务名称，如 '电商运营'、'HR 人事'。"""

    @property
    @abstractmethod
    def column_aliases(self) -> dict[str, list[str]]:
        """canonical 字段 -> 可能出现的列名（含中英文别名，全部小写比较）。
        每个 canonical 的第一个别名作为「中文展示标签」。
        """

    @property
    @abstractmethod
    def key_fields(self) -> list[str]:
        """关键字段（canonical），缺失时在数据质量报告中告警。"""

    @property
    def time_columns(self) -> set[str]:
        """需要转为 datetime 的 canonical 列（子类可覆盖）。"""
        return set()

    @property
    def numeric_columns(self) -> set[str]:
        """需要转为数值的 canonical 列（子类可覆盖）。"""
        return set()

    # ── 异常检测（子类必须实现）─────────────────────────────────────────────────

    @abstractmethod
    def run_checks(self, df: Any, cfg: Any = None) -> list[CheckResult]:
        """对规整后的 DataFrame 跑所有异常检测，返回结构化结果列表。

        df: 已按 column_aliases 规整为 canonical 列名的 DataFrame。
        cfg: app/config.py 的 Config 实例（含阈值），可选。
        """

    # ── 报告生成（子类必须实现）─────────────────────────────────────────────────

    @abstractmethod
    def get_system_prompt(self) -> str:
        """LLM 日报生成的 system prompt，定义角色、输出风格和板块要求。"""

    @abstractmethod
    def get_report_sections(self) -> list[str]:
        """报告板块名称列表（顺序即输出顺序），与 system_prompt 保持一致。"""

    @abstractmethod
    def build_mock_report(self, analysis: dict) -> str:
        """不依赖真实 LLM，用确定性模板渲染完整报告（用于离线/回退场景）。"""

    # ── 工具方法（基类提供默认实现，子类可覆盖）─────────────────────────────────

    @property
    def canonical_labels(self) -> dict[str, str]:
        """canonical -> 中文展示标签（取各 canonical 别名列表的第一个）。"""
        return {k: v[0] for k, v in self.column_aliases.items()}

    def build_analysis_dict(self, results: list[CheckResult], df_len: int, now: Any) -> dict:
        """把 run_checks 的结果组装成标准 analysis dict，供报告节点消费。

        格式与现有 analyzer.analyze_orders 的返回值兼容，保证报告层零改动。
        """
        from datetime import datetime
        now = now or datetime.now()
        categories: dict[str, list[dict]] = {}
        category_titles: dict[str, str] = {}
        skipped: list[str] = []
        skipped_keys: list[str] = []

        for r in results:
            categories[r.check_key] = r.items
            category_titles[r.check_key] = r.title
            if r.skip_reason:
                skipped.append(f"{r.title}：{r.skip_reason}")
                skipped_keys.append(r.check_key)

        summary = {k: len(v) for k, v in categories.items()}
        # 兼容不同业务域的主键字段名（order_id / employee_id / invoice_id …）
        distinct = {
            it.get("record_id") or it.get("order_id", "")
            for items in categories.values()
            for it in items
        }

        return {
            "date": now.strftime("%Y-%m-%d"),
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "total_orders": int(df_len),
            "anomaly_total": int(sum(summary.values())),
            "anomaly_orders": len(distinct),
            "summary": summary,
            "category_titles": category_titles,
            "categories": categories,
            "skipped_checks": skipped,
            "skipped_keys": skipped_keys,
        }
