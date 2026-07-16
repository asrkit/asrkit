"""High-level API: transcribe / pull / run / list_models."""
from __future__ import annotations

from typing import Any, Callable, Iterator, List, Optional, Union, cast

from . import registry

from .types import (
    AdapterMeta,
    AudioInput,
    BaseAdapter,
    PartialResult,
    TranscribeOptions,
    TranscribeResult,
)

def _run_adapter(
    adapter: BaseAdapter,
    model: str,
    audio: Union[str, AudioInput],
    opts: Optional[TranscribeOptions],
) -> TranscribeResult:
    if not adapter.is_configured():
        return TranscribeResult(
            text="", error=f"{model} is not configured (missing API key?). See docs/usage.md")
    if isinstance(audio, str):
        audio = AudioInput(original_path=audio)   # 内核零处理：不解码，adapter 各取所需
    opts = opts or TranscribeOptions()
    result = adapter.transcribe(audio, opts)
    from . import capabilities
    w = capabilities.warnings_for(opts, adapter.meta)
    if w:
        result.warnings = (result.warnings or []) + w
    return result


def transcribe(
    model: str,
    audio: Union[str, AudioInput],
    *,
    config: Optional[dict[str, Any]] = None,
    opts: Optional[TranscribeOptions] = None,
) -> TranscribeResult:
    """换个 model 字符串即切换端/云模型。"""
    return _run_adapter(registry.make_adapter(model, config or {}), model, audio, opts)


def pull(
    model: str,
    *,
    config: Optional[dict[str, Any]] = None,
    url: Optional[str] = None,
    log: Callable[[str], Any] = print,
) -> str:
    """安装一个模型/引擎（本地下载权重或引擎；云端无需）。url 可覆盖默认下载地址。返回位置。"""
    return cast(str, registry.make_adapter(model, config or {}).install(log=log, url=url))


def run(
    model: str,
    audio: Union[str, AudioInput],
    *,
    config: Optional[dict[str, Any]] = None,
    opts: Optional[TranscribeOptions] = None,
    log: Callable[[str], Any] = print,
) -> TranscribeResult:
    """Ollama 式一步到位：本地缺失则先安装，再转写（同一 adapter 实例）。"""
    adapter = registry.make_adapter(model, config or {})
    if not adapter.is_installed():
        adapter.install(log=log)
    return _run_adapter(adapter, model, audio, opts)


def list_models() -> List[AdapterMeta]:
    return cast(List[AdapterMeta], registry.list_metas())


def show(model: str) -> AdapterMeta:
    """解析模型 id/别名/裸名为其 AdapterMeta（未注册则抛 ModelNotFoundError）。"""
    return cast(AdapterMeta, registry.resolve(model))


def remove(
    model: str, *, config: Optional[dict[str, Any]] = None
) -> Optional[str]:
    """删除 ASRKit 管理的模型缓存，返回被删目录（未缓存则 None）。"""
    return cast(Optional[str], registry.make_adapter(model, config or {}).remove_cached_model())


def _streaming_adapter(
    model: str, config: Optional[dict[str, Any]]
) -> BaseAdapter:
    adapter = registry.make_adapter(model, config or {})
    if "streaming" not in adapter.meta.modes:
        raise ValueError(f"{model} is not a streaming model")
    if not adapter.is_configured():
        raise ValueError(f"{model} is not configured (missing API key?)")
    return cast(BaseAdapter, adapter)


def transcribe_stream(
    model: str,
    audio: str,
    *,
    config: Optional[dict[str, Any]] = None,
    opts: Optional[TranscribeOptions] = None,
    window_s: float = 0.1,
) -> Iterator[PartialResult]:
    """流式转写(文件分块)。仅 streaming 模型;及早校验。"""
    if window_s <= 0:
        raise ValueError("window_s must be > 0")
    adapter = _streaming_adapter(model, config)
    opts = opts or TranscribeOptions()
    from . import audio as _audio
    chunks = _audio.iter_file_chunks(audio, 16000, 1, window_s, convert=opts.convert)
    return adapter.transcribe_stream(chunks, opts)


def transcribe_stream_mic(
    model: str,
    *,
    config: Optional[dict[str, Any]] = None,
    opts: Optional[TranscribeOptions] = None,
    samplerate: int = 16000,
    block_s: float = 0.1,
    device: Any = None,
) -> Iterator[PartialResult]:
    """麦克风实时流式转写。仅 streaming 模型;需 asrkit[mic];Ctrl-C 停。"""
    adapter = _streaming_adapter(model, config)
    opts = opts or TranscribeOptions()
    from . import mic as _mic
    chunks = _mic.record_chunks(samplerate=samplerate, block_s=block_s, device=device)
    return adapter.transcribe_stream(chunks, opts)
