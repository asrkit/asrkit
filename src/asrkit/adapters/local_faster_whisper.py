"""faster-whisper engine adapter (optional: pip install "asrkit[faster-whisper]").

Models are auto-downloaded & cached by faster-whisper from HuggingFace
(~/.cache/huggingface), not asrkit's ~/.asrkit/models. Transparent: the original
file is handed straight to the engine (it does its own decoding & long-audio chunking).
"""
from __future__ import annotations

import importlib.util
import time

from ..registry import register_models, register_protocol
from ..types import AdapterMeta, AudioInput, BaseAdapter, TranscribeOptions, TranscribeResult

_INSTALL_HINT = 'engine \'faster-whisper\' not installed. Run: pip install "asrkit[faster-whisper]"'


def _available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


@register_protocol("faster-whisper")
class FasterWhisper(BaseAdapter):
    def __init__(self, meta, config=None):
        super().__init__(meta, config)
        self._model = None

    def is_installed(self) -> bool:
        return _available()

    def install(self, log=print, url=None) -> str:
        if not _available():
            raise RuntimeError(_INSTALL_HINT)
        from faster_whisper import WhisperModel
        log(f"loading {self.meta.model} (downloads from HuggingFace on first use) ...")
        WhisperModel(self.meta.model)   # triggers download + cache
        log("done")
        return f"faster-whisper:{self.meta.model} (HuggingFace cache)"

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        if not _available():
            return TranscribeResult(text="", error=_INSTALL_HINT)
        try:
            from faster_whisper import WhisperModel
            t0 = time.perf_counter()
            if self._model is None:
                self._model = WhisperModel(self.meta.model, device="auto", compute_type="int8")
            load_ms = int((time.perf_counter() - t0) * 1000)

            t1 = time.perf_counter()
            # 引擎自带解码 + 长音频分块，原始文件直接给它（透明）
            segments, info = self._model.transcribe(
                audio.original_path, language=opts.lang_hint or None)
            text = "".join(s.text for s in segments).strip()
            decode_ms = int((time.perf_counter() - t1) * 1000)
            return TranscribeResult(
                text=text, lang=getattr(info, "language", None),
                latency_ms=load_ms + decode_ms,
                metrics={"load_ms": load_ms, "decode_ms": decode_ms})
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")


# —— faster-whisper 模型（provider=faster-whisper；model=faster-whisper 名，自动从 HF 下载）——
_FW = [
    ("tiny", "Whisper tiny (faster-whisper)", ["zh", "en"]),
    ("base", "Whisper base (faster-whisper)", ["zh", "en"]),
    ("small", "Whisper small (faster-whisper)", ["zh", "en"]),
    ("medium", "Whisper medium (faster-whisper)", ["zh", "en"]),
    ("large-v3", "Whisper large-v3 (faster-whisper)", ["zh", "en"]),
    ("large-v3-turbo", "Whisper large-v3-turbo (faster-whisper)", ["zh", "en"]),
    ("distil-large-v3", "Distil-Whisper large-v3 (faster-whisper)", ["en"]),
]

register_models([
    AdapterMeta(
        id=f"faster-whisper/{name}",
        provider="faster-whisper",
        vendor="faster-whisper",
        name=disp,
        source="local",
        modes=["batch"],
        langs=langs,
        model_kind="asr",
        config_type="whisper",
        model=name,
        # faster-whisper 自带长音频分块，无 30s 窗口限制，故不设 max_input_duration_s
    )
    for name, disp, langs in _FW
])
