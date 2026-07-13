"""进程级内置 adapter 加载 profile。"""
from __future__ import annotations

import importlib


def load(name: str) -> None:
    """按名称加载一个内置 profile；具体模块负责显式导入其 adapter。"""
    module = importlib.import_module(f"{__name__}.{name}")
    module.load()
