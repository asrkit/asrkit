"""发现任务单元测试（T1: multilingual 标记 + sensevoice langs；T2: list --lang/--arch）。"""
import json as _json

from asrkit import cli, registry


def _run(args, capsys):
    rc = cli.main(args)
    return rc, capsys.readouterr().out


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


def test_list_lang_multilingual_and_explicit(capsys):
    _, out = _run(["list", "--lang", "ja", "--source", "local", "--json"], capsys)
    ids = {d["id"] for d in _json.loads(out)}
    assert "local/whisper-tiny" in ids          # multilingual flag
    assert "local/sensevoice" in ids            # 显式 ja
    assert "local/whisper-tiny-en" not in ids   # en-only
    assert "local/paraformer-zh" not in ids     # zh-only 非多语


def test_list_lang_normalizes_case(capsys):
    _, out = _run(["list", "--lang", "YUE", "--source", "local", "--json"], capsys)
    ids = {d["id"] for d in _json.loads(out)}
    assert "local/sensevoice" in ids            # 归一化大写


def test_list_arch_case_insensitive(capsys):
    _, out1 = _run(["list", "--arch", "senseVoice", "--json"], capsys)
    _, out2 = _run(["list", "--arch", "sensevoice", "--json"], capsys)
    ids1 = {d["id"] for d in _json.loads(out1)}
    ids2 = {d["id"] for d in _json.loads(out2)}
    assert ids1 == ids2 and "local/sensevoice" in ids1


def test_list_no_filter_json_shape(capsys):
    _, out = _run(["list", "--json"], capsys)
    data = _json.loads(out)
    pz = next(d for d in data if d["id"] == "local/paraformer-zh")
    assert set(pz) >= {"id", "name", "source", "provider", "vendor", "langs",
                       "model_kind", "installed", "size_bytes"}


def test_search_matches_id_name(capsys):
    _, out = _run(["search", "whisper", "--json"], capsys)
    ids = {d["id"] for d in _json.loads(out)}
    assert "openai/whisper-1" in ids and "faster-whisper/large-v3" in ids
    assert any(i.startswith("local/whisper") for i in ids)


def test_search_empty(capsys):
    _, out = _run(["search", "zzznomatch", "--json"], capsys)
    assert _json.loads(out) == []


def test_show_multilingual_line(capsys):
    _, out = _run(["show", "local/whisper-tiny"], capsys)
    assert "multilingual: yes" in out
    _, out2 = _run(["show", "local/paraformer-zh"], capsys)
    assert "multilingual: no" in out2
