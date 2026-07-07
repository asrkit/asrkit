import uuid

from asrkit import _http, registry
from asrkit.types import AudioInput, TranscribeOptions


class _R:
    def __init__(self, status=200, headers=None, jsonobj=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self._j = jsonobj or {}
        self.text = text

    def json(self):
        return self._j


def test_doubao_uuid_and_policies(tmp_path, monkeypatch):
    from asrkit.adapters import cloud_doubao
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw.get("idempotent"), kw["headers"]["X-Api-Request-Id"]))
        if url.endswith("/submit"):
            return _R(200)
        return _R(200, headers={"x-api-status-code": "20000000"},
                  jsonobj={"result": {"text": "hi"}})

    monkeypatch.setattr(_http, "post", fake_post)
    monkeypatch.setattr(cloud_doubao.time, "sleep", lambda s: None)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    a = registry.make_adapter("doubao/auc-2", {"api_key": "k"})
    r = a.transcribe(AudioInput(original_path=str(wav)), TranscribeOptions())
    assert r.text == "hi"
    submit = next(c for c in calls if c[0].endswith("/submit"))
    query = next(c for c in calls if c[0].endswith("/query"))
    assert submit[1] is False and query[1] is True     # 分策略
    assert submit[2] == query[2]                        # 同一 request-id
    uuid.UUID(submit[2])                                # 是合法 uuid
