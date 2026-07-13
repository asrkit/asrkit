"""Python 完整发行物使用的全部内置 adapter 与模型表。"""
from __future__ import annotations


def load() -> None:
    from ..adapters import (  # noqa: F401
        cloud_dashscope,
        cloud_doubao,
        cloud_elevenlabs,
        cloud_openai,
        local_faster_whisper,
        local_sherpa,
        local_transformers,
        local_whispercpp,
        models_local,
    )
