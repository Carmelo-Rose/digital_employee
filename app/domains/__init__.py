"""业务域注册表。

新增业务域步骤：
  1. 在本目录新建 my_domain.py，实现 BusinessDomain 的所有抽象方法。
  2. 在 DOMAIN_REGISTRY 中注册：{"my_domain": MyDomain}。
  3. 启动时传 domain_name="my_domain" 即可，无需改动任何节点或图编排代码。
"""
from __future__ import annotations

from .base import BusinessDomain, CheckResult, DomainConfig
from .ecommerce import EcommerceDomain
from .general import GeneralDomain
from .hr import HRDomain

__all__ = ["BusinessDomain", "CheckResult", "DomainConfig", "DOMAIN_REGISTRY", "get_domain"]

DOMAIN_REGISTRY: dict[str, type[BusinessDomain]] = {
    "ecommerce": EcommerceDomain,
    "hr": HRDomain,
    "general": GeneralDomain,
}


def get_domain(name: str | None = None) -> BusinessDomain:
    """工厂函数：按名称返回业务域实例。name 为 None 或未知时返回通用域。"""
    key = (name or "ecommerce").lower().strip()
    cls = DOMAIN_REGISTRY.get(key)
    if cls is None:
        return GeneralDomain()
    return cls()
