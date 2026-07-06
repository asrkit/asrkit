"""高层 API：transcribe(model=..., audio=...)。"""
from __future__ import annotations

from typing import List, Optional, Union

from . import registry
from .audio import load_audio
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
    if isinstance(audio, str):
        audio = load_audio(audio)
    return adapter.transcribe(audio, opts or TranscribeOptions())


def list_models() -> List[AdapterMeta]:
    return registry.list_metas()
