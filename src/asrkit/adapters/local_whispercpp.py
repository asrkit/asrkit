"""whisper.cpp engine adapter (optional: pip install "asrkit[whispercpp]").

Ultra-light Whisper via whisper.cpp (GGML) through the pywhispercpp binding.
Models auto-downloaded & cached by pywhispercpp. No torch / onnxruntime.
"""
from __future__ import annotations

import importlib.util
import time

from ..audio import AudioFormatError, load_samples
from ..registry import register_models, register_protocol
from ..types import AdapterMeta, AudioInput, BaseAdapter, TranscribeOptions, TranscribeResult

_INSTALL_HINT = 'engine \'whispercpp\' not installed. Run: pip install "asrkit[whispercpp]"'


def _available() -> bool:
    return importlib.util.find_spec("pywhispercpp") is not None


@register_protocol("whispercpp")
class WhisperCpp(BaseAdapter):
    def __init__(self, meta, config=None):
        super().__init__(meta, config)
        self._model = None

    def is_installed(self) -> bool:
        return _available()

    def install(self, log=print) -> str:
        if not _available():
            raise RuntimeError(_INSTALL_HINT)
        from pywhispercpp.model import Model
        log(f"loading {self.meta.model} (downloads GGML on first use) ...")
        Model(self.meta.model)
        log("done")
        return f"whispercpp:{self.meta.model} (whisper.cpp cache)"

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        if not _available():
            return TranscribeResult(text="", error=_INSTALL_HINT)
        try:
            from pywhispercpp.model import Model
            # whisper.cpp 需要 16k 单声道，用我们的解码器备好（引擎必需的输入格式）
            try:
                samples, _ = load_samples(audio.original_path, 16000, 1, convert=True)
            except AudioFormatError as e:
                return TranscribeResult(text="", error=str(e))

            t0 = time.perf_counter()
            if self._model is None:
                self._model = Model(self.meta.model)
            load_ms = int((time.perf_counter() - t0) * 1000)

            t1 = time.perf_counter()
            segs = self._model.transcribe(samples)
            text = " ".join(getattr(s, "text", "") for s in segs).strip()
            decode_ms = int((time.perf_counter() - t1) * 1000)
            return TranscribeResult(
                text=text, latency_ms=load_ms + decode_ms,
                metrics={"load_ms": load_ms, "decode_ms": decode_ms})
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")


_WC = [
    ("tiny", "Whisper tiny (whisper.cpp)", ["zh", "en"]),
    ("base", "Whisper base (whisper.cpp)", ["zh", "en"]),
    ("small", "Whisper small (whisper.cpp)", ["zh", "en"]),
    ("medium", "Whisper medium (whisper.cpp)", ["zh", "en"]),
    ("large-v3", "Whisper large-v3 (whisper.cpp)", ["zh", "en"]),
]

register_models([
    AdapterMeta(
        id=f"whispercpp/{name}", provider="whispercpp", vendor="whispercpp",
        name=disp, source="local", modes=["batch"], langs=langs,
        model_kind="asr", config_type="whisper", model=name)
    for name, disp, langs in _WC
])
