"""Tests for doubao polling deadline/backoff (longrun robustness)."""
from asrkit.adapters import cloud_doubao


def test_poll_timeout_env_fallbacks(monkeypatch):
    """非法/非有限/<=0 → 回退 300.0;合法正数 → 采用。"""
    for bad in ["inf", "nan", "abc", "0", "-5", ""]:
        monkeypatch.setenv("ASRKIT_DOUBAO_POLL_TIMEOUT_S", bad)
        assert cloud_doubao._poll_timeout_s() == 300.0
    monkeypatch.delenv("ASRKIT_DOUBAO_POLL_TIMEOUT_S", raising=False)
    assert cloud_doubao._poll_timeout_s() == 300.0
    monkeypatch.setenv("ASRKIT_DOUBAO_POLL_TIMEOUT_S", "120")
    assert cloud_doubao._poll_timeout_s() == 120.0


class _Resp:
    def __init__(self, status_code=200, headers=None, payload=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}
        self.text = text
    def json(self):
        return self._payload


def _make_adapter():
    from asrkit import registry
    return registry.make_adapter("doubao/auc-2", {"app_key": "k", "access_key": "s"})


def _wav(tmp_path):
    """已知扩展名的真实文件(内容无所谓,_http 全 mock)。"""
    p = tmp_path / "clip.wav"
    p.write_bytes(b"RIFF0000WAVE")
    return str(p)


def test_poll_late_success_not_truncated_at_30(monkeypatch, tmp_path):
    """第 40 次 query 才成功(>30)——不再被 30 次硬限截断。"""
    monkeypatch.setattr(cloud_doubao.time, "sleep", lambda *_: None)
    calls = {"n": 0}
    def fake_post(url, **kw):
        if url.endswith("/submit"):
            return _Resp(status_code=200)
        calls["n"] += 1
        if calls["n"] >= 40:
            return _Resp(headers={"x-api-status-code": "20000000"},
                         payload={"result": {"text": "done late"}})
        return _Resp(headers={"x-api-status-code": "20000001"})   # 处理中
    monkeypatch.setattr(cloud_doubao._http, "post", fake_post)
    from asrkit.types import AudioInput, TranscribeOptions
    ad = _make_adapter()
    r = ad.transcribe(AudioInput(original_path=_wav(tmp_path)), TranscribeOptions())
    assert r.error is None or r.error == ""
    assert r.text == "done late"
    assert calls["n"] >= 40


def test_poll_timeout_reports_actual_value(monkeypatch, tmp_path):
    """恒处理中 + 超时很小 → 报实际超时值,不无限轮询。"""
    monkeypatch.setattr(cloud_doubao.time, "sleep", lambda *_: None)
    monkeypatch.setattr(cloud_doubao, "_poll_timeout_s", lambda: 7.0)
    seq = iter([0.0, 1.0, 100.0, 200.0, 300.0])
    monkeypatch.setattr(cloud_doubao.time, "perf_counter", lambda: next(seq))
    def fake_post(url, **kw):
        if url.endswith("/submit"):
            return _Resp(status_code=200)
        return _Resp(headers={"x-api-status-code": "20000001"})
    monkeypatch.setattr(cloud_doubao._http, "post", fake_post)
    from asrkit.types import AudioInput, TranscribeOptions
    ad = _make_adapter()
    r = ad.transcribe(AudioInput(original_path=_wav(tmp_path)), TranscribeOptions())
    assert r.error and "doubao polling timeout (7s)" in r.error


def test_poll_terminal_error_returns_early(monkeypatch, tmp_path):
    """query 返回 45xx 终态错误码 → 立即 query failed,不等超时、不再轮询。"""
    monkeypatch.setattr(cloud_doubao.time, "sleep", lambda *_: None)
    calls = {"n": 0}
    def fake_post(url, **kw):
        if url.endswith("/submit"):
            return _Resp(status_code=200)
        calls["n"] += 1
        return _Resp(headers={"x-api-status-code": "45000001"}, text="bad request")
    monkeypatch.setattr(cloud_doubao._http, "post", fake_post)
    from asrkit.types import AudioInput, TranscribeOptions
    ad = _make_adapter()
    r = ad.transcribe(AudioInput(original_path=_wav(tmp_path)), TranscribeOptions())
    assert r.error and "query failed code=45000001" in r.error
    assert calls["n"] == 1                     # 第一次 query 即返回,不继续轮询
