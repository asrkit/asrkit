"""0.5.0：asrkit serve —— OpenAI 兼容端点。需 asrkit[serve]，未装则跳过。"""
import io
import wave

import pytest

from asrkit import registry, server
from asrkit.types import AdapterMeta, BaseAdapter, PartialResult, TranscribeResult


@pytest.fixture
def client(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")  # python-multipart
    pytest.importorskip("httpx")      # TestClient 依赖（CI 装 asrkit[dev] 提供）
    from fastapi.testclient import TestClient
    from asrkit import server

    # 注册一个 stub adapter/模型，避免真实推理
    @registry.register_protocol("stub-serve")
    class _Stub(BaseAdapter):
        def transcribe(self, audio, opts):
            return TranscribeResult(text="hello from stub", lang="en")

    registry.register_model(AdapterMeta(
        id="stub/echo", provider="stub-serve", vendor="stub", name="Stub",
        source="cloud", modes=["batch"], langs=["en"]))
    return TestClient(server.build_app())


def _wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    return buf.getvalue()


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_models_list(client):
    data = client.get("/v1/models").json()
    assert data["object"] == "list"
    assert any(m["id"] == "stub/echo" for m in data["data"])


def test_transcription_json(client):
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "stub/echo"},
                    files={"file": ("a.wav", _wav_bytes(), "audio/wav")})
    assert r.status_code == 200
    assert r.json()["text"] == "hello from stub"


def test_unknown_model_404(client):
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "does/not-exist"},
                    files={"file": ("a.wav", _wav_bytes(), "audio/wav")})
    assert r.status_code == 404


def _reset_cache():
    server._ADAPTERS.clear()


def test_serve_cache_hit_no_rebuild(monkeypatch):
    _reset_cache()
    calls = {"n": 0}
    def fake_make(model, *a, **k):
        calls["n"] += 1
        return object()
    monkeypatch.setattr(server.registry, "make_adapter", fake_make)
    a1 = server._get_adapter("m")
    a2 = server._get_adapter("m")
    assert a1 is a2 and calls["n"] == 1


def test_serve_cache_bounded_lru_evicts(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(server, "_cache_size", lambda: 2)
    monkeypatch.setattr(server.registry, "make_adapter", lambda model, *a, **k: object())
    server._get_adapter("A")
    server._get_adapter("B")
    server._get_adapter("C")
    assert len(server._ADAPTERS) == 2 and "A" not in server._ADAPTERS
    calls = {"n": 0}
    def counting(model, *a, **k):
        calls["n"] += 1
        return object()
    monkeypatch.setattr(server.registry, "make_adapter", counting)
    server._get_adapter("A")
    assert calls["n"] == 1


def test_serve_cache_hit_refreshes_lru(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(server, "_cache_size", lambda: 2)
    monkeypatch.setattr(server.registry, "make_adapter", lambda model, *a, **k: object())
    server._get_adapter("A")
    server._get_adapter("B")
    server._get_adapter("A")            # 命中 A → A 最近
    server._get_adapter("C")            # 淘汰最久未用 = B
    assert "A" in server._ADAPTERS and "B" not in server._ADAPTERS


def test_serve_cache_exception_not_cached(monkeypatch):
    _reset_cache()
    def boom(model, *a, **k):
        raise server.registry.ModelNotFoundError("nope")
    monkeypatch.setattr(server.registry, "make_adapter", boom)
    with pytest.raises(server.registry.ModelNotFoundError):
        server._get_adapter("bad")
    assert "bad" not in server._ADAPTERS


def test_serve_cache_size_env_fallbacks(monkeypatch):
    for bad in ["abc", "0", "-3", ""]:
        monkeypatch.setenv("ASRKIT_SERVE_CACHE", bad)
        assert server._cache_size() == 8
    monkeypatch.delenv("ASRKIT_SERVE_CACHE", raising=False)
    assert server._cache_size() == 8
    monkeypatch.setenv("ASRKIT_SERVE_CACHE", "16")
    assert server._cache_size() == 16


# ---- stream=true SSE（P3-D） -------------------------------------------------

def _fake_adapter(modes, partials):
    """构造一个假 adapter：忽略 chunks，直接吐脚本化 PartialResult 序列。"""
    class _A:
        class meta:  # 简化：仅需 meta.modes 属性
            pass

        def transcribe_stream(self, chunks, opts):
            return iter(partials)

    a = _A()
    a.meta = type("M", (), {"modes": modes})()
    return a


def test_stream_sse_happy_path(client, monkeypatch):
    partials = [
        PartialResult(text="he", committed="", partial="he"),
        PartialResult(text="hello world", committed="hello world", partial="", is_final=True),
    ]
    monkeypatch.setattr(server, "_get_adapter",
                        lambda model: _fake_adapter(["streaming"], partials))
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "stub/echo", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert '"type": "transcript.text.delta"' in body
    assert '"delta": "hello world"' in body  # 首个 delta = "" -> "hello world"
    assert '"type": "transcript.text.done"' in body
    assert '"text": "hello world"' in body
    assert "data: [DONE]" in body


def test_stream_non_streaming_model_400(client, monkeypatch):
    monkeypatch.setattr(server, "_get_adapter",
                        lambda model: _fake_adapter(["batch"], []))
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "stub/echo", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 400
    assert "not a streaming model" in r.json()["error"]["message"]


def test_stream_unknown_model_404(client, monkeypatch):
    def boom(model):
        raise server.registry.ModelNotFoundError("nope")
    monkeypatch.setattr(server, "_get_adapter", boom)
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "does/not-exist", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 404


def test_stream_setup_broad_exception_500(client, monkeypatch):
    def boom(model):
        raise RuntimeError("plugin load failed")
    monkeypatch.setattr(server, "_get_adapter", boom)
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "stub/echo", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 500


def test_stream_error_event(client, monkeypatch):
    partials = [PartialResult(text="", is_final=True, error="boom")]
    monkeypatch.setattr(server, "_get_adapter",
                        lambda model: _fake_adapter(["streaming"], partials))
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "stub/echo", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 200
    body = r.text
    assert '"type": "error"' in body
    assert "boom" in body
    assert "data: [DONE]" in body


def test_stream_delta_defense_non_append(client, monkeypatch):
    # committed 非追加（"ab" -> "xy"）：不应崩，最终 done 仍带全文
    partials = [
        PartialResult(text="ab", committed="ab", partial=""),
        PartialResult(text="xy", committed="xy", partial="", is_final=True),
    ]
    monkeypatch.setattr(server, "_get_adapter",
                        lambda model: _fake_adapter(["streaming"], partials))
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "stub/echo", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 200
    body = r.text
    assert '"type": "transcript.text.done"' in body
    assert '"text": "xy"' in body
    assert "data: [DONE]" in body
