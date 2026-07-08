"""High-level API: transcribe / pull / run / list_models."""
from __future__ import annotations

from typing import List

from . import registry
from .types import AdapterMeta, AudioInput, TranscribeOptions, TranscribeResult


def _run_adapter(adapter, model, audio, opts):
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


def transcribe(model, audio, *, config=None, opts=None):
    """换个 model 字符串即切换端/云模型。"""
    return _run_adapter(registry.make_adapter(model, config or {}), model, audio, opts)


def pull(model, *, config=None, url=None, log=print):
    """安装一个模型/引擎（本地下载权重或引擎；云端无需）。url 可覆盖默认下载地址。返回位置。"""
    return registry.make_adapter(model, config or {}).install(log=log, url=url)


def run(model, audio, *, config=None, opts=None, log=print):
    """Ollama 式一步到位：本地缺失则先安装，再转写（同一 adapter 实例）。"""
    adapter = registry.make_adapter(model, config or {})
    if not adapter.is_installed():
        adapter.install(log=log)
    return _run_adapter(adapter, model, audio, opts)


def list_models() -> List[AdapterMeta]:
    return registry.list_metas()


def show(model: str) -> AdapterMeta:
    """解析模型 id/别名/裸名为其 AdapterMeta（未注册则抛 ModelNotFoundError）。"""
    return registry.resolve(model)


def remove(model: str, *, config=None):
    """删除已下载的本地模型，返回被删目录（未装则 None）。仅本地模型。"""
    from . import store
    meta = registry.resolve(model)
    if meta.source != "local":
        raise ValueError(f"{model} is not a local model; nothing to remove")
    return store.remove(meta, config or {})


def _streaming_adapter(model, config):
    adapter = registry.make_adapter(model, config or {})
    if "streaming" not in adapter.meta.modes:
        raise ValueError(f"{model} is not a streaming model")
    if not adapter.is_configured():
        raise ValueError(f"{model} is not configured (missing API key?)")
    return adapter


def transcribe_stream(model, audio, *, config=None, opts=None, window_s=0.1):
    """流式转写(文件分块)。仅 streaming 模型;及早校验。"""
    if window_s <= 0:
        raise ValueError("window_s must be > 0")
    adapter = _streaming_adapter(model, config)
    opts = opts or TranscribeOptions()
    from . import audio as _audio
    chunks = _audio.iter_file_chunks(audio, 16000, 1, window_s, convert=opts.convert)
    return adapter.transcribe_stream(chunks, opts)


def transcribe_stream_mic(model, *, config=None, opts=None,
                          samplerate=16000, block_s=0.1, device=None):
    """麦克风实时流式转写。仅 streaming 模型;需 asrkit[mic];Ctrl-C 停。"""
    adapter = _streaming_adapter(model, config)
    opts = opts or TranscribeOptions()
    from . import mic as _mic
    chunks = _mic.record_chunks(samplerate=samplerate, block_s=block_s, device=device)
    return adapter.transcribe_stream(chunks, opts)
