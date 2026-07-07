"""发现任务单元测试（T1: multilingual 标记 + sensevoice langs）。"""
from asrkit import registry


def _caps(mid):
    return registry.resolve(mid).capabilities or {}


def test_multilingual_marked():
    for mid in ["local/whisper-tiny", "local/omnilingual-300m", "local/qwen3-asr-0.6b",
                "local/funasr-nano", "local/dolphin-small",
                "faster-whisper/large-v3", "whispercpp/base", "openai/whisper-1"]:
        assert _caps(mid).get("multilingual") is True, mid


def test_multilingual_not_marked():
    for mid in ["local/whisper-tiny-en", "local/moonshine-tiny",
                "faster-whisper/distil-large-v3", "local/paraformer-zh"]:
        assert not _caps(mid).get("multilingual"), mid


def test_sensevoice_precise_langs_no_flag():
    m = registry.resolve("local/sensevoice")
    assert "ja" in m.langs and "ko" in m.langs      # 补全
    assert not (m.capabilities or {}).get("multilingual")   # 精确,不打 flag
