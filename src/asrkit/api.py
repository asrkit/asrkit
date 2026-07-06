"""高层 API：transcribe / pull / run / list_models。"""
from __future__ import annotations

from typing import List, Optional, Union

from . import registry, store
from .types import AdapterMeta, AudioInput, TranscribeOptions, TranscribeResult


def transcribe(
    model: str,
    audio: Union[str, AudioInput],
    *,
    config: Optional[dict] = None,
    opts: Optional[TranscribeOptions] = None,
) -> TranscribeResult:
    """换个 model 字符串即切换端/云模型。"""
    adapter = registry.make_adapter(model, config or {})
    if not adapter.is_configured():   # H-18：缺配置（如云端无 key）先给友好错误
        return TranscribeResult(
            text="", error=f"{model} 未配置（缺 API Key？）。see docs/usage.md")
    if isinstance(audio, str):
        audio = AudioInput(original_path=audio)   # 内核零处理：不解码，adapter 各取所需
    return adapter.transcribe(audio, opts or TranscribeOptions())


def pull(model: str, *, config: Optional[dict] = None, log=print) -> str:
    """下载并安装一个本地模型（Ollama 式）。返回模型目录。"""
    meta = registry.resolve(model)
    if meta.source != "local":
        raise ValueError(f"{model} 是云端模型，无需下载（配置 API Key 即可用）。")
    return store.pull(meta, config or {}, log=log)


def run(
    model: str,
    audio: Union[str, AudioInput],
    *,
    config: Optional[dict] = None,
    opts: Optional[TranscribeOptions] = None,
    log=print,
) -> TranscribeResult:
    """Ollama 式一步到位：本地模型缺失则先下载，再转写。"""
    meta = registry.resolve(model)
    if meta.source == "local" and not store.is_installed(meta, config or {}):
        pull(model, config=config, log=log)
    return transcribe(model, audio, config=config, opts=opts)


def list_models() -> List[AdapterMeta]:
    return registry.list_metas()
