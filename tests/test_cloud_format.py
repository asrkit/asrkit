"""云端 adapter 如实声明音频容器格式(透明原则):不再硬编码 wav。

内核对音频零处理,上传时把真实容器格式据实上报;未知扩展名诚实报错,
绝不静默谎报为 wav(否则 mp3/flac 上传会被云端当 wav 解出乱码)。
"""
import pytest

from asrkit.audio import AudioFormatError, container_format
from asrkit.types import AudioInput, TranscribeOptions


class _Resp:
    def __init__(self, status_code=200, headers=None, payload=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_container_format_known_extensions():
    assert container_format("/x/a.wav") == "wav"
    assert container_format("/x/a.mp3") == "mp3"
    assert container_format("/x/a.FLAC") == "flac"      # 大小写无关
    assert container_format("/x/a.m4a") == "m4a"
    assert container_format("/x/a.ogg") == "ogg"


def test_container_format_unknown_errors():
    for bad in ["/x/a.py", "/x/noext", "/x/a.txt"]:
        with pytest.raises(AudioFormatError):
            container_format(bad)


def test_doubao_declares_true_format_not_wav(tmp_path, monkeypatch):
    """传 mp3 → submit 的 audio.format == 'mp3'(此前恒 'wav')。"""
    from asrkit import registry
    from asrkit.adapters import cloud_doubao
    captured = {}

    def fake_post(url, **kw):
        if url.endswith("/submit"):
            captured["json"] = kw.get("json")
            return _Resp(status_code=200)
        return _Resp(headers={"x-api-status-code": "20000000"},
                     payload={"result": {"text": "ok"}})

    monkeypatch.setattr(cloud_doubao.time, "sleep", lambda *_: None)
    monkeypatch.setattr(cloud_doubao._http, "post", fake_post)
    ad = registry.make_adapter("doubao/auc-2", {"app_key": "k", "access_key": "s"})
    p = tmp_path / "clip.mp3"
    p.write_bytes(b"ID3xxxx")
    r = ad.transcribe(AudioInput(original_path=str(p)), TranscribeOptions())
    assert r.error in (None, "")
    assert captured["json"]["audio"]["format"] == "mp3"


def test_doubao_unknown_format_honest_error_no_submit(tmp_path, monkeypatch):
    """未知扩展名 → 诚实报错,绝不上传谎报的 wav。"""
    from asrkit import registry
    from asrkit.adapters import cloud_doubao

    def fake_post(url, **kw):
        raise AssertionError("must not upload for an unknown format")

    monkeypatch.setattr(cloud_doubao._http, "post", fake_post)
    ad = registry.make_adapter("doubao/auc-2", {"app_key": "k", "access_key": "s"})
    p = tmp_path / "clip.xyz"
    p.write_bytes(b"xxxx")
    r = ad.transcribe(AudioInput(original_path=str(p)), TranscribeOptions())
    assert not r.text
    assert r.error and "format" in r.error.lower()


def test_funasr_declares_true_format_and_no_faked_rate(tmp_path, monkeypatch):
    """传 mp3 → parameters.format == 'mp3',且不再谎报 sample_rate=16000。"""
    from asrkit import registry
    from asrkit.adapters import cloud_dashscope
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["body"] = json
        return _Resp(status_code=200, payload={"output": {"text": "ok"}})

    monkeypatch.setattr(cloud_dashscope._http, "post", fake_post)
    ad = registry.make_adapter("dashscope/fun-asr-flash", {"api_key": "k"})
    p = tmp_path / "clip.mp3"
    p.write_bytes(b"ID3xxxx")
    r = ad.transcribe(AudioInput(original_path=str(p)), TranscribeOptions())
    assert r.error in (None, "")
    params = captured["body"]["parameters"]
    assert params["format"] == "mp3"
    assert "sample_rate" not in params


def test_funasr_unknown_format_honest_error(tmp_path, monkeypatch):
    """未知扩展名 → data URI 阶段就诚实报错。"""
    from asrkit import registry
    from asrkit.adapters import cloud_dashscope

    def fake_post(url, **kw):
        raise AssertionError("must not upload for an unknown format")

    monkeypatch.setattr(cloud_dashscope._http, "post", fake_post)
    ad = registry.make_adapter("dashscope/fun-asr-flash", {"api_key": "k"})
    p = tmp_path / "clip.xyz"
    p.write_bytes(b"xxxx")
    r = ad.transcribe(AudioInput(original_path=str(p)), TranscribeOptions())
    assert not r.text
    assert r.error and "format" in r.error.lower()
