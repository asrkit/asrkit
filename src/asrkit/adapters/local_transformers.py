"""transformers engine adapter (optional: pip install "asrkit[transformers]").

Runs ANY HuggingFace ASR model via the transformers ASR pipeline — including
LLM-architecture SOTA models. Open addressing: transformers/<hf-model-id>
(e.g. transformers/openai/whisper-large-v3, transformers/nvidia/canary-qwen-2.5b).
Heavy (torch); large SOTA models realistically want a GPU. The original file is
handed straight to the pipeline (engine does its own decoding & long-audio chunking).
"""
from __future__ import annotations

import importlib.util
import time

from ..registry import register_models, register_open_provider, register_protocol
from ..types import AdapterMeta, AudioInput, BaseAdapter, TranscribeOptions, TranscribeResult

_INSTALL_HINT = 'engine \'transformers\' not installed. Run: pip install "asrkit[transformers]"'


def _available() -> bool:
    return (importlib.util.find_spec("transformers") is not None
            and importlib.util.find_spec("torch") is not None)


def _meta_for(model_str: str) -> AdapterMeta:
    """把任意 HF 模型 id 合成一个 transformers meta（开放 provider）。"""
    return AdapterMeta(
        id=f"transformers/{model_str}",
        provider="transformers",
        vendor="transformers",
        name=f"{model_str} (transformers)",
        source="local",
        modes=["batch"],
        langs=[],
        model_kind="asr",
        config_type="hf-asr",
        model=model_str,
    )


@register_protocol("transformers")
class Transformers(BaseAdapter):
    def __init__(self, meta, config=None):
        super().__init__(meta, config)
        self._pipe = None

    def is_installed(self) -> bool:
        return _available()

    def install(self, log=print) -> str:
        if not _available():
            raise RuntimeError(_INSTALL_HINT)
        from transformers import pipeline
        log(f"loading {self.meta.model} (downloads from HuggingFace on first use) ...")
        pipeline("automatic-speech-recognition", model=self.meta.model)
        log("done")
        return f"transformers:{self.meta.model} (HuggingFace cache)"

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        if not _available():
            return TranscribeResult(text="", error=_INSTALL_HINT)
        try:
            import torch
            from transformers import pipeline
            t0 = time.perf_counter()
            if self._pipe is None:
                device = 0 if torch.cuda.is_available() else -1
                self._pipe = pipeline(
                    "automatic-speech-recognition", model=self.meta.model,
                    chunk_length_s=30, device=device)   # chunk → 支持长音频
            load_ms = int((time.perf_counter() - t0) * 1000)

            t1 = time.perf_counter()
            out = self._pipe(audio.original_path)   # 引擎自解码/分块，原始文件直接给它
            text = (out.get("text") if isinstance(out, dict) else str(out)).strip()
            decode_ms = int((time.perf_counter() - t1) * 1000)
            return TranscribeResult(
                text=text, latency_ms=load_ms + decode_ms,
                metrics={"load_ms": load_ms, "decode_ms": decode_ms})
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")


# 开放 provider：transformers/<任意 HF id> 都能用
register_open_provider("transformers", _meta_for)

# 少量精选便于 `asrkit list` 发现；其余用 transformers/<任意 HF 模型 id>
register_models([
    _meta_for("openai/whisper-large-v3"),
    _meta_for("openai/whisper-tiny"),
])
