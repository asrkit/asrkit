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


def test_whispercpp_fills_segments_centiseconds_and_language(monkeypatch):
    from asrkit.adapters import local_whispercpp as wc

    seen = {}

    class _Seg:
        def __init__(self, t0, t1, text):
            self.t0, self.t1, self.text = t0, t1, text

    class _Model:
        def __init__(self, *a, **k):
            pass
        def transcribe(self, samples, language=None):
            seen["language"] = language
            return [_Seg(150, 320, " hello")]          # 厘秒:1.5s, 3.2s

    fake_mod = types.ModuleType("pywhispercpp.model")
    fake_mod.Model = _Model
    fake_pkg = types.ModuleType("pywhispercpp")
    monkeypatch.setitem(sys.modules, "pywhispercpp", fake_pkg)
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", fake_mod)
    monkeypatch.setattr(wc, "_available", lambda: True)
    monkeypatch.setattr(wc, "load_samples", lambda *a, **k: ([0.0], 16000))

    a = registry.make_adapter("whispercpp/tiny")
    r = a.transcribe(AudioInput(original_path="x.wav"), TranscribeOptions(lang_hint="en"))
    assert r.text == "hello"
    assert r.segments and r.segments[0].start == 1.5 and r.segments[0].end == 3.2   # 厘秒/100
    assert seen["language"] == "en"                    # language 透传(不再静默丢)


def test_whispercpp_meta_capabilities():
    m = registry.resolve("whispercpp/tiny")
    assert m.capabilities.get("segment_timestamps") is True
    assert m.capabilities.get("language_hint") == "supported"
