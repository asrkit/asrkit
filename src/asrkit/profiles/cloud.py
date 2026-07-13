"""asrkitd 使用的 cloud-only adapter 集。"""
from __future__ import annotations


def load() -> None:
    from ..adapters import (  # noqa: F401
        cloud_dashscope,
        cloud_doubao,
        cloud_elevenlabs,
        cloud_openai,
    )
