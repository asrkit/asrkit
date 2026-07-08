"""测试 capabilities 三态归一 + api 告警接线。"""
from asrkit import api, capabilities, registry
from asrkit.types import AdapterMeta, BaseAdapter, TranscribeOptions, TranscribeResult


def _meta(lang):
    caps = {"language_hint": lang} if lang is not None else {}
    return AdapterMeta(id="x/y", provider="p", vendor="v", name="n",
                       source="cloud", modes=["batch"], langs=[], capabilities=caps)


def test_language_tristate():
    assert capabilities.language_supported(_meta("supported"))
    assert capabilities.language_supported(_meta("required"))
    assert not capabilities.language_supported(_meta("none"))
    assert not capabilities.language_supported(_meta(None))
    assert capabilities.language_ignored(_meta("none"))
    assert not capabilities.language_ignored(_meta("supported"))
    assert not capabilities.language_ignored(_meta(None))


def test_warnings_only_when_ignored_and_lang_passed():
    o = TranscribeOptions(lang_hint="zh")
    assert capabilities.warnings_for(o, _meta("none"))
    assert not capabilities.warnings_for(o, _meta("supported"))
    assert not capabilities.warnings_for(o, _meta(None))
    assert not capabilities.warnings_for(TranscribeOptions(), _meta("none"))   # 没传 lang


def test_sherpa_capabilities_by_arch():
    assert registry.resolve("sherpa/sensevoice").capabilities.get("language_hint") == "none"
    assert registry.resolve("sherpa/whisper-tiny").capabilities.get("language_hint") == "supported"
    # sherpa whisper 不标 segment_timestamps(不填 sherpa segments)
    assert "segment_timestamps" not in registry.resolve("sherpa/whisper-tiny").capabilities


def test_api_appends_language_warning():
    @registry.register_protocol("stub-warn")
    class _Stub(BaseAdapter):
        def transcribe(self, audio, opts):
            return TranscribeResult(text="hi")
    registry.register_model(AdapterMeta(
        id="stub/warn", provider="stub-warn", vendor="stub", name="s",
        source="cloud", modes=["batch"], langs=[], capabilities={"language_hint": "none"}))
    r = api.transcribe("stub/warn", "a.wav", opts=TranscribeOptions(lang_hint="zh"))
    assert any("ignored" in w for w in (r.warnings or []))
