import sys
import types

from asrkit import registry
from asrkit.types import AudioInput, TranscribeOptions


class _R:                       # 假 HTTP 响应(openai 测试用)
    def __init__(self, status=200, jsonobj=None):
        self.status_code = status
        self._j = jsonobj or {}
        self.text = ""
    def json(self):
        return self._j


def test_faster_whisper_fills_segments_and_materializes(monkeypatch):
    from asrkit.adapters import local_faster_whisper as fw

    class _Seg:
        def __init__(self, start, end, text):
            self.start, self.end, self.text = start, end, text

    class _Info:
        language = "en"

    class _Model:
        def __init__(self, *a, **k):
            pass
        def transcribe(self, path, language=None):
            gen = (s for s in [_Seg(0.0, 1.0, " hi"), _Seg(1.0, 2.0, " there")])  # 生成器
            return gen, _Info()

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _Model
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.setattr(fw, "_available", lambda: True)

    a = registry.make_adapter("faster-whisper/tiny")
    r = a.transcribe(AudioInput(original_path="x.wav"), TranscribeOptions())
    assert r.text == "hi there"                        # 物化后 text 不丢
    assert r.segments and len(r.segments) == 2
    assert r.segments[0].start == 0.0 and r.segments[0].text == "hi"


def test_faster_whisper_meta_capabilities():
    m = registry.resolve("faster-whisper/tiny")
    assert m.capabilities.get("segment_timestamps") is True
    assert m.capabilities.get("language_hint") == "supported"
