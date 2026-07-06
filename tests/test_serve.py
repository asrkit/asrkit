"""0.5.0：asrkit serve —— OpenAI 兼容端点。需 asrkit[serve]，未装则跳过。"""
import io
import wave

import pytest

from asrkit import registry
from asrkit.types import AdapterMeta, BaseAdapter, TranscribeResult


@pytest.fixture
def client(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")  # python-multipart
    from fastapi.testclient import TestClient  # 需 httpx
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
