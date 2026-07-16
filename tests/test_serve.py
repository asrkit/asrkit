"""0.5.0：asrkit serve —— OpenAI 兼容端点。需 asrkit[serve]，未装则跳过。"""
import asyncio
import io
import threading
import time
import wave
from concurrent.futures import Future, ThreadPoolExecutor

import pytest

from asrkit import registry, server
from asrkit.types import AdapterMeta, BaseAdapter, PartialResult, Segment, TranscribeResult


@pytest.fixture(autouse=True)
def _register_stub_model():
    """每个测试都显式建立最小 registry 前提，不依赖文件执行顺序。"""
    @registry.register_protocol("stub-serve")
    class _Stub(BaseAdapter):
        def transcribe(self, audio, opts):
            return TranscribeResult(text="hello from stub", lang="en")

    registry.register_model(AdapterMeta(
        id="stub/echo", provider="stub-serve", vendor="stub", name="Stub",
        source="cloud", modes=["batch", "streaming"], langs=["en"]))


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")  # python-multipart
    pytest.importorskip("httpx")      # TestClient 依赖（CI 装 asrkit[dev] 提供）
    from fastapi.testclient import TestClient

    with TestClient(server.build_app()) as test_client:
        yield test_client


def test_uvicorn_transport_is_explicit_and_http_only():
    assert server._uvicorn_transport_options() == {
        "loop": "asyncio",
        "http": "h11",
        "ws": "none",
    }


def test_direct_serve_applies_safe_resource_defaults(monkeypatch):
    import uvicorn

    seen = {}
    app = object()
    monkeypatch.setattr(
        server, "build_app", lambda **kwargs: seen.update(kwargs) or app)
    monkeypatch.setattr(uvicorn, "run", lambda received, **kwargs: seen.update(app=received))

    server.serve()

    assert seen["app"] is app
    assert seen["max_upload_bytes"] == 200 * 1024 * 1024
    assert seen["max_concurrency"] == 4
    assert seen["request_timeout_s"] == 300.0


def test_request_limiter_release_is_safe_from_worker_thread():
    limiter = server._RequestLimiter(2)

    async def exercise():
        assert await limiter.try_acquire() is True
        assert await limiter.try_acquire() is True
        assert await limiter.try_acquire() is False

        release_thread = threading.Thread(target=limiter.release)
        release_thread.start()
        release_thread.join()

        assert await limiter.try_acquire() is True
        limiter.release()
        limiter.release()

    asyncio.run(exercise())


def test_request_permit_unpins_from_concurrent_future_thread():
    limiter = server._RequestLimiter(1)
    assert asyncio.run(limiter.try_acquire()) is True
    permit = server._RequestPermit(limiter)
    future = Future()
    permit.pin(future)
    permit.finish_response()

    worker = threading.Thread(target=future.set_result, args=(None,))
    worker.start()
    worker.join()

    assert asyncio.run(limiter.try_acquire()) is True
    limiter.release()


def test_daemon_executor_shutdown_is_bounded_while_worker_is_stuck():
    started = threading.Event()
    release = threading.Event()

    def blocked():
        started.set()
        assert release.wait(2)
        return "done"

    executor = server._DaemonExecutor(1, thread_name_prefix="asrkit-test")
    future = executor.submit(blocked)
    assert started.wait(2)
    assert all(thread.daemon for thread in executor._threads)

    before = time.monotonic()
    executor.shutdown(wait=False)
    assert time.monotonic() - before < 0.1
    release.set()
    assert future.result(timeout=2) == "done"


def _wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    return buf.getvalue()


async def _post_when_permit_available(client, *, data, timeout=2):
    """worker 先 unlink 再完成 Future；以 HTTP permit 事实而非临时目录作同步。"""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        response = await client.post(
            "/v1/audio/transcriptions",
            data=data,
            files={"file": ("a.wav", b"audio", "audio/wav")},
        )
        if response.status_code != 429:
            return response
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.01)


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


def test_secure_server_auth_and_health_metadata():
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    token = "x" * 32
    app = server.build_app(
        auth_token=token,
        health_info={"version": "test", "protocol_version": 1, "distribution": "cloud"},
    )
    with TestClient(app) as secure:
        assert secure.get("/health").json() == {
            "status": "ok", "version": "test",
            "protocol_version": 1, "distribution": "cloud",
        }
        unauthorized = secure.get("/v1/models")
        assert unauthorized.status_code == 401
        assert unauthorized.json() == {"error": {"message": "unauthorized"}}
        assert unauthorized.headers["www-authenticate"] == "Bearer"
        assert secure.get(
            "/v1/models", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_upload_limit_returns_413_and_cleans_temp_dir(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    app = server.build_app(max_upload_bytes=4, temp_dir=str(tmp_path))
    with TestClient(app) as limited:
        response = limited.post(
            "/v1/audio/transcriptions",
            data={"model": "stub/echo"},
            files={"file": ("a.wav", b"12345", "audio/wav")},
        )
    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_request_timeout_defers_cleanup_until_worker_finishes(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    calls = {"n": 0}
    first_started = threading.Event()
    first_release = threading.Event()

    class _Adapter:
        def transcribe(self, audio, opts):
            calls["n"] += 1
            if calls["n"] == 1:
                first_started.set()
                assert first_release.wait(2)
            return TranscribeResult(text="done")

    monkeypatch.setattr(server.registry, "make_adapter", lambda model: _Adapter())
    app = server.build_app(
        max_concurrency=1, request_timeout_s=0.01, temp_dir=str(tmp_path))
    with TestClient(app) as timed:
        first = timed.post(
            "/v1/audio/transcriptions",
            data={"model": "stub/echo"},
            files={"file": ("a.wav", b"audio", "audio/wav")},
        )
        assert first.status_code == 504
        assert first_started.is_set()
        assert list(tmp_path.iterdir()) != []

        # HTTP 已超时不代表同步 worker 已结束；permit 仍必须被占用。
        still_busy = timed.post(
            "/v1/audio/transcriptions",
            data={"model": "stub/echo"},
            files={"file": ("a.wav", b"audio", "audio/wav")},
        )
        assert still_busy.status_code == 429

        first_release.set()
        deadline = time.time() + 2
        while list(tmp_path.iterdir()) and time.time() < deadline:
            time.sleep(0.01)
        assert list(tmp_path.iterdir()) == []

        deadline = time.time() + 2
        while True:
            second = timed.post(
                "/v1/audio/transcriptions",
                data={"model": "stub/echo"},
                files={"file": ("a.wav", b"audio", "audio/wav")},
            )
            if second.status_code != 429:
                break
            assert time.time() < deadline
            time.sleep(0.01)
        assert second.status_code == 200


def test_concurrency_limit_rejects_without_queueing(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    started = threading.Event()
    release = threading.Event()

    class _Adapter:
        def transcribe(self, audio, opts):
            started.set()
            assert release.wait(2)
            return TranscribeResult(text="done")

    monkeypatch.setattr(server.registry, "make_adapter", lambda model: _Adapter())
    app = server.build_app(
        max_concurrency=1, request_timeout_s=5, temp_dir=str(tmp_path))
    with TestClient(app) as limited, ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            limited.post,
            "/v1/audio/transcriptions",
            data={"model": "stub/echo"},
            files={"file": ("a.wav", b"audio", "audio/wav")},
        )
        assert started.wait(2)
        second = limited.post(
            "/v1/audio/transcriptions",
            data={"model": "stub/echo"},
            files={"file": ("a.wav", b"audio", "audio/wav")},
        )
        assert second.status_code == 429
        release.set()
        assert first.result(timeout=5).status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_worker_500_releases_permit_and_tempfile(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    calls = 0

    class _Adapter:
        def transcribe(self, audio, opts):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("provider failed")
            return TranscribeResult(text="recovered")

    monkeypatch.setattr(server.registry, "make_adapter", lambda model: _Adapter())
    app = server.build_app(max_concurrency=1, temp_dir=str(tmp_path))
    with TestClient(app) as test_client:
        first = test_client.post(
            "/v1/audio/transcriptions",
            data={"model": "stub/echo"},
            files={"file": ("a.wav", b"audio", "audio/wav")},
        )
        second = test_client.post(
            "/v1/audio/transcriptions",
            data={"model": "stub/echo"},
            files={"file": ("a.wav", b"audio", "audio/wav")},
        )
    assert first.status_code == 500
    assert second.status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_request_cancellation_pins_worker_permit_and_tempfile(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    httpx = pytest.importorskip("httpx")

    started = threading.Event()
    release = threading.Event()
    calls = 0

    class _Adapter:
        def transcribe(self, audio, opts):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                assert release.wait(2)
            return TranscribeResult(text="done")

    monkeypatch.setattr(server.registry, "make_adapter", lambda model: _Adapter())
    app = server.build_app(max_concurrency=1, temp_dir=str(tmp_path))

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                    transport=transport, base_url="http://test") as client:
                request = asyncio.create_task(client.post(
                    "/v1/audio/transcriptions",
                    data={"model": "stub/echo"},
                    files={"file": ("a.wav", b"audio", "audio/wav")},
                ))
                assert await asyncio.to_thread(started.wait, 2)
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request

                while not list(tmp_path.iterdir()):
                    await asyncio.sleep(0.001)
                busy = await client.post(
                    "/v1/audio/transcriptions",
                    data={"model": "stub/echo"},
                    files={"file": ("a.wav", b"audio", "audio/wav")},
                )
                assert busy.status_code == 429

                release.set()
                deadline = asyncio.get_running_loop().time() + 2
                while list(tmp_path.iterdir()) and asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(0.01)
                recovered = await _post_when_permit_available(
                    client, data={"model": "stub/echo"})
                assert recovered.status_code == 200

    asyncio.run(scenario())
    assert list(tmp_path.iterdir()) == []


def test_cancellation_during_adapter_build_keeps_concurrency_permit(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    httpx = pytest.importorskip("httpx")

    meta = _meta()
    started = threading.Event()
    release = threading.Event()
    made = 0

    class _Adapter:
        def is_configured(self):
            return True

        def transcribe(self, audio, opts):
            return TranscribeResult(text="done")

    def factory(model):
        nonlocal made
        assert model == meta.id
        made += 1
        started.set()
        assert release.wait(2)
        return _Adapter()

    monkeypatch.setattr(server.registry, "resolve", lambda model: meta)
    monkeypatch.setattr(server.registry, "make_adapter", factory)
    app = server.build_app(max_concurrency=1)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                    transport=transport, base_url="http://test") as client:
                first = asyncio.create_task(client.post(
                    "/v1/audio/transcriptions",
                    data={"model": "stub/echo"},
                    files={"file": ("a.wav", b"audio", "audio/wav")},
                ))
                assert await asyncio.to_thread(started.wait, 2)
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first

                busy = await client.post(
                    "/v1/audio/transcriptions",
                    data={"model": "stub/echo"},
                    files={"file": ("a.wav", b"audio", "audio/wav")},
                )
                assert busy.status_code == 429

                release.set()
                recovered = await _post_when_permit_available(
                    client, data={"model": "stub/echo"})
                assert recovered.status_code == 200

    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert made == 1


def test_sse_disconnect_pins_resources_until_stream_worker_stops(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    httpx = pytest.importorskip("httpx")

    meta = _meta(modes=["streaming"])
    started = threading.Event()
    release = threading.Event()
    calls = 0

    class _StreamingAdapter:
        def __init__(self):
            self.meta = meta

        def is_configured(self):
            return True

        def transcribe_stream(self, chunks, opts):
            nonlocal calls
            calls += 1
            yield PartialResult(text="first", committed="first")
            if calls == 1:
                started.set()
                assert release.wait(2)
            yield PartialResult(
                text="first done", committed="first done", is_final=True)

    monkeypatch.setattr(server.registry, "resolve", lambda model: meta)
    monkeypatch.setattr(
        server.registry, "make_adapter", lambda model: _StreamingAdapter())
    app = server.build_app(max_concurrency=1, temp_dir=str(tmp_path))

    request = httpx.Request(
        "POST", "http://test/v1/audio/transcriptions",
        data={"model": "stub/echo", "stream": "true"},
        files={"file": ("a.wav", b"audio", "audio/wav")},
    )
    body = request.read()
    request_headers = [(name.lower(), value) for name, value in request.headers.raw]

    async def disconnected_call():
        sent = []
        body_delivered = False
        never = asyncio.Event()

        async def receive():
            nonlocal body_delivered
            if not body_delivered:
                body_delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await never.wait()

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                raise asyncio.CancelledError

        await app(_scope(headers=request_headers), receive, send)

    async def rejected_while_busy():
        sent = []
        reads = 0

        async def receive():
            nonlocal reads
            reads += 1
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            sent.append(message)

        await app(_scope(headers=request_headers), receive, send)
        return sent, reads

    async def scenario():
        async with app.router.lifespan_context(app):
            await disconnected_call()
            assert await asyncio.to_thread(started.wait, 2)
            assert list(tmp_path.iterdir())

            busy, reads = await rejected_while_busy()
            assert _status(busy) == 429
            assert reads == 0

            release.set()
            deadline = asyncio.get_running_loop().time() + 2
            while list(tmp_path.iterdir()) and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                    transport=transport, base_url="http://test") as client:
                recovered = await _post_when_permit_available(
                    client,
                    data={"model": "stub/echo", "stream": "true"},
                )
            assert recovered.status_code == 200
            assert "data: [DONE]" in recovered.text

    asyncio.run(scenario())
    assert list(tmp_path.iterdir()) == []


def test_serve_cache_size_env_fallbacks(monkeypatch):
    for bad in ["abc", "0", "-3", ""]:
        monkeypatch.setenv("ASRKIT_SERVE_CACHE", bad)
        assert server._cache_size() == 8
    monkeypatch.delenv("ASRKIT_SERVE_CACHE", raising=False)
    assert server._cache_size() == 8
    monkeypatch.setenv("ASRKIT_SERVE_CACHE", "16")
    assert server._cache_size() == 16


def _meta(*, modes=None, capabilities=None):
    return AdapterMeta(
        id="stub/echo", provider="stub-serve", vendor="stub", name="Stub",
        source="cloud", modes=modes or ["batch"], langs=["en"],
        capabilities=capabilities or {},
    )


def _post(app, *, response_format=None, stream=None, body=b"audio"):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    data = {"model": "stub/echo"}
    if response_format is not None:
        data["response_format"] = response_format
    if stream is not None:
        data["stream"] = str(stream).lower()
    with TestClient(app) as test_client:
        return test_client.post(
            "/v1/audio/transcriptions",
            data=data,
            files={"file": ("a.wav", body, "audio/wav")},
        )


def test_invalid_response_format_precedes_registry_adapter_and_tempfile(tmp_path, monkeypatch):
    monkeypatch.setattr(
        server.registry, "resolve",
        lambda model: pytest.fail("invalid format must not resolve a model"),
    )
    monkeypatch.setattr(
        server.registry, "make_adapter",
        lambda model: pytest.fail("invalid format must not create an adapter"),
    )
    response = _post(
        server.build_app(temp_dir=str(tmp_path)), response_format="yaml")
    assert response.status_code == 400
    assert "unknown response_format" in response.json()["error"]["message"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("modes", "stream", "message"),
    [(["streaming"], False, "does not support batch"),
     (["batch"], True, "not a streaming model")],
)
def test_mode_mismatch_precedes_adapter_and_transcribe(
        tmp_path, monkeypatch, modes, stream, message):
    monkeypatch.setattr(server.registry, "resolve", lambda model: _meta(modes=modes))
    monkeypatch.setattr(
        server.registry, "make_adapter",
        lambda model: pytest.fail("mode mismatch must not create an adapter"),
    )
    response = _post(server.build_app(temp_dir=str(tmp_path)), stream=stream)
    assert response.status_code == 400
    assert message in response.json()["error"]["message"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("capability", [None, False])
def test_subtitle_format_requires_explicit_timestamp_capability(
        tmp_path, monkeypatch, capability):
    capabilities = {} if capability is None else {"segment_timestamps": capability}
    monkeypatch.setattr(
        server.registry, "resolve", lambda model: _meta(capabilities=capabilities))
    monkeypatch.setattr(
        server.registry, "make_adapter",
        lambda model: pytest.fail("unsupported subtitle must not create an adapter"),
    )
    response = _post(
        server.build_app(temp_dir=str(tmp_path)), response_format="srt")
    assert response.status_code == 400
    assert "does not declare segment timestamps" in response.json()["error"]["message"]
    assert list(tmp_path.iterdir()) == []


def test_missing_configuration_precedes_audio_copy_and_transcribe(tmp_path, monkeypatch):
    calls = {"transcribe": 0}

    class _Unconfigured:
        meta = _meta()

        def is_configured(self):
            return False

        def transcribe(self, audio, opts):
            calls["transcribe"] += 1
            return TranscribeResult(text="must not run")

    monkeypatch.setattr(server.registry, "resolve", lambda model: _meta())
    monkeypatch.setattr(server.registry, "make_adapter", lambda model: _Unconfigured())
    response = _post(server.build_app(temp_dir=str(tmp_path)))
    assert response.status_code == 400
    assert "not configured" in response.json()["error"]["message"]
    assert calls["transcribe"] == 0
    assert list(tmp_path.iterdir()) == []


def test_subtitle_is_allowed_only_when_capability_is_explicitly_true(tmp_path, monkeypatch):
    meta = _meta(capabilities={"segment_timestamps": True})

    class _Timestamped:
        def __init__(self):
            self.meta = meta

        def is_configured(self):
            return True

        def transcribe(self, audio, opts):
            return TranscribeResult(
                text="hello", segments=[Segment(start=0.0, end=1.0, text="hello")])

    monkeypatch.setattr(server.registry, "resolve", lambda model: meta)
    monkeypatch.setattr(server.registry, "make_adapter", lambda model: _Timestamped())
    response = _post(
        server.build_app(temp_dir=str(tmp_path)), response_format="srt")
    assert response.status_code == 200
    assert "00:00:00,000 --> 00:00:01,000" in response.text
    assert list(tmp_path.iterdir()) == []


def test_exact_file_limit_succeeds(tmp_path, monkeypatch):
    meta = _meta()

    class _Adapter:
        def __init__(self):
            self.meta = meta

        def is_configured(self):
            return True

        def transcribe(self, audio, opts):
            return TranscribeResult(text="ok")

    monkeypatch.setattr(server.registry, "resolve", lambda model: meta)
    monkeypatch.setattr(server.registry, "make_adapter", lambda model: _Adapter())
    response = _post(
        server.build_app(max_upload_bytes=5, temp_dir=str(tmp_path)), body=b"12345")
    assert response.status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_batch_without_timeout_still_runs_in_explicit_worker_future(tmp_path, monkeypatch):
    meta = _meta()
    worker_names = []

    class _Adapter:
        def __init__(self):
            self.meta = meta

        def is_configured(self):
            return True

        def transcribe(self, audio, opts):
            worker_names.append(threading.current_thread().name)
            return TranscribeResult(text="ok")

    monkeypatch.setattr(server.registry, "resolve", lambda model: meta)
    monkeypatch.setattr(server.registry, "make_adapter", lambda model: _Adapter())
    response = _post(server.build_app(temp_dir=str(tmp_path)))
    assert response.status_code == 200
    assert len(worker_names) == 1
    assert worker_names[0].startswith("asrkit-serve")


def test_adapter_cache_is_scoped_to_each_app(monkeypatch):
    meta = _meta()
    made = []

    class _Adapter:
        def __init__(self):
            self.meta = meta
            self.closed = 0

        def is_configured(self):
            return True

        def transcribe(self, audio, opts):
            return TranscribeResult(text="ok")

        def close(self):
            self.closed += 1

    def factory(model):
        adapter = _Adapter()
        made.append(adapter)
        return adapter

    monkeypatch.setattr(server.registry, "resolve", lambda model: meta)
    monkeypatch.setattr(server.registry, "make_adapter", factory)
    assert _post(server.build_app()).status_code == 200
    assert _post(server.build_app()).status_code == 200
    assert len(made) == 2
    assert [adapter.closed for adapter in made] == [1, 1]


def test_configuration_check_obeys_serialized_adapter_contract():
    call_entered = threading.Event()
    call_release = threading.Event()
    configured_entered = threading.Event()

    class _SerializedAdapter:
        def supports_concurrent_calls(self):
            return False

        def blocking_call(self):
            call_entered.set()
            assert call_release.wait(2)

        def is_configured(self):
            configured_entered.set()
            return True

    manager = server._AdapterManager(lambda _model: _SerializedAdapter(), capacity=1)
    active = manager.lease("canonical/model")
    with ThreadPoolExecutor(max_workers=2) as pool:
        blocking = pool.submit(active.invoke, "blocking_call")
        assert call_entered.wait(2)
        checking = pool.submit(server._acquire_configured, manager, "canonical/model")
        assert not configured_entered.wait(0.05)
        call_release.set()
        blocking.result(timeout=2)
        configured_lease = checking.result(timeout=2)

    assert configured_entered.is_set()
    configured_lease.release()
    active.release()
    assert manager.shutdown(timeout=1) is True


def test_model_aliases_share_one_canonical_adapter_slot(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    meta = _meta()
    made = 0

    class _Adapter:
        def __init__(self):
            self.meta = meta

        def is_configured(self):
            return True

        def transcribe(self, audio, opts):
            return TranscribeResult(text="ok")

    def factory(model):
        nonlocal made
        assert model == meta.id
        made += 1
        return _Adapter()

    monkeypatch.setattr(server.registry, "resolve", lambda model: meta)
    monkeypatch.setattr(server.registry, "make_adapter", factory)
    app = server.build_app()
    with TestClient(app) as test_client:
        for alias in ("echo", "legacy/echo", "stub/echo"):
            response = test_client.post(
                "/v1/audio/transcriptions",
                data={"model": alias},
                files={"file": ("a.wav", b"audio", "audio/wav")},
            )
            assert response.status_code == 200
    assert made == 1


def _scope(*, headers=(), root_path=""):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/audio/transcriptions",
        "raw_path": b"/v1/audio/transcriptions",
        "root_path": root_path,
        "query_string": b"",
        "headers": list(headers),
        "client": ("test", 1),
        "server": ("test", 80),
    }


async def _call_asgi(app, *, scope=None, messages=None):
    sent = []
    reads = 0
    pending = list(messages or [{"type": "http.request", "body": b"", "more_body": False}])

    async def receive():
        nonlocal reads
        reads += 1
        if pending:
            return pending.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope or _scope(), receive, send)
    return sent, reads


def _status(sent):
    return next(message["status"] for message in sent
                if message["type"] == "http.response.start")


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"-1")],
        [(b"content-length", b"not-a-number")],
        [(b"content-length", b"3"), (b"content-length", b"4")],
        [(b"content-length", b"3, 4")],
        [(b"content-length", b"9" * 5000)],
        [(b"content-length", b"3"), (b"transfer-encoding", b"chunked")],
    ],
)
def test_asgi_gate_rejects_ambiguous_content_length_before_downstream(headers):
    called = 0

    async def downstream(scope, receive, send):
        nonlocal called
        called += 1

    gate = server._EntryGateMiddleware(
        downstream, auth_token=None, max_upload_bytes=1,
        limiter=server._RequestLimiter(1))
    sent, reads = asyncio.run(_call_asgi(gate, scope=_scope(headers=headers)))
    assert _status(sent) == 400
    assert called == 0
    assert reads == 0


def test_asgi_gate_accepts_equal_content_lengths_and_preserves_scope_state():
    seen_state = None

    async def downstream(scope, receive, send):
        nonlocal seen_state
        seen_state = scope["state"]
        await receive()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    gate = server._EntryGateMiddleware(
        downstream, auth_token=None, max_upload_bytes=1,
        limiter=server._RequestLimiter(1))
    scope = _scope(headers=[(b"content-length", b"0"),
                            (b"content-length", b"0")])
    scope["state"] = {"existing": "kept"}
    sent, _ = asyncio.run(_call_asgi(gate, scope=scope))
    assert _status(sent) == 204
    assert seen_state["existing"] == "kept"
    assert isinstance(seen_state["_asrkit_permit"], server._RequestPermit)


def test_asgi_gate_rejects_oversized_content_length_with_root_path():
    called = 0
    limit = server._MULTIPART_OVERHEAD_BYTES + 1

    async def downstream(scope, receive, send):
        nonlocal called
        called += 1

    gate = server._EntryGateMiddleware(
        downstream, auth_token=None, max_upload_bytes=1,
        limiter=server._RequestLimiter(1))
    scope = _scope(
        headers=[(b"content-length", str(limit + 1).encode())], root_path="/proxy")
    sent, reads = asyncio.run(_call_asgi(gate, scope=scope))
    assert _status(sent) == 413
    assert called == 0
    assert reads == 0


def test_asgi_gate_counts_chunked_multi_frame_body():
    async def downstream(scope, receive, send):
        while True:
            message = await receive()
            if message["type"] == "http.disconnect" or not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    gate = server._EntryGateMiddleware(
        downstream, auth_token=None, max_upload_bytes=1,
        limiter=server._RequestLimiter(1))
    messages = [
        {"type": "http.request", "body": b"x" * server._MULTIPART_OVERHEAD_BYTES,
         "more_body": True},
        {"type": "http.request", "body": b"xx", "more_body": False},
    ]
    sent, _ = asyncio.run(_call_asgi(
        gate,
        scope=_scope(headers=[(b"transfer-encoding", b"chunked")]),
        messages=messages,
    ))
    assert _status(sent) == 413


def test_asgi_gate_auth_precedes_size_permit_and_body_read():
    called = 0

    async def downstream(scope, receive, send):
        nonlocal called
        called += 1

    gate = server._EntryGateMiddleware(
        downstream, auth_token="secret", max_upload_bytes=1,
        limiter=server._RequestLimiter(1))
    sent, reads = asyncio.run(_call_asgi(
        gate,
        scope=_scope(headers=[(b"content-length", b"99999999")]),
    ))
    assert _status(sent) == 401
    assert called == 0
    assert reads == 0


def test_asgi_gate_rejects_browser_origin_before_permit_and_body_read():
    called = 0
    limiter = server._RequestLimiter(1)

    async def downstream(scope, receive, send):
        nonlocal called
        called += 1

    async def scenario():
        gate = server._EntryGateMiddleware(
            downstream, auth_token=None, max_upload_bytes=1, limiter=limiter)
        sent, reads = await _call_asgi(
            gate,
            scope=_scope(headers=[(b"origin", b"https://evil.example")]),
        )
        available = await limiter.try_acquire()
        if available:
            limiter.release()
        return sent, reads, available

    sent, reads, available = asyncio.run(scenario())
    assert _status(sent) == 403
    assert called == 0
    assert reads == 0
    assert available is True


def test_asgi_gate_rejects_duplicate_authorization_headers():
    called = 0

    async def downstream(scope, receive, send):
        nonlocal called
        called += 1

    gate = server._EntryGateMiddleware(
        downstream, auth_token="secret", max_upload_bytes=1,
        limiter=server._RequestLimiter(1))
    sent, reads = asyncio.run(_call_asgi(
        gate,
        scope=_scope(headers=[
            (b"authorization", b"Bearer secret"),
            (b"authorization", b"Bearer secret"),
        ]),
    ))
    assert _status(sent) == 401
    assert called == 0
    assert reads == 0


def test_asgi_gate_429_does_not_enter_downstream_or_read_body():
    called = 0
    limiter = server._RequestLimiter(1)

    async def downstream(scope, receive, send):
        nonlocal called
        called += 1

    async def scenario():
        assert await limiter.try_acquire() is True
        gate = server._EntryGateMiddleware(
            downstream, auth_token=None, max_upload_bytes=1, limiter=limiter)
        try:
            return await _call_asgi(gate)
        finally:
            limiter.release()

    sent, reads = asyncio.run(scenario())
    assert _status(sent) == 429
    assert called == 0
    assert reads == 0


def test_asgi_disconnect_releases_permit_for_next_request():
    limiter = server._RequestLimiter(1)

    async def downstream(scope, receive, send):
        assert (await receive())["type"] == "http.disconnect"
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def scenario():
        gate = server._EntryGateMiddleware(
            downstream, auth_token=None, max_upload_bytes=1, limiter=limiter)
        disconnect = [{"type": "http.disconnect"}]
        first, _ = await _call_asgi(gate, messages=disconnect)
        second, _ = await _call_asgi(gate, messages=disconnect)
        return first, second

    first, second = asyncio.run(scenario())
    assert _status(first) == _status(second) == 400


# ---- stream=true SSE（P3-D） -------------------------------------------------

def _fake_adapter(modes, partials):
    """构造一个假 adapter：忽略 chunks，直接吐脚本化 PartialResult 序列。"""
    class _A:
        class meta:  # 简化：仅需 meta.modes 属性
            pass

        def transcribe_stream(self, chunks, opts):
            return iter(partials)

        def is_configured(self):
            return True

    a = _A()
    a.meta = type("M", (), {"modes": modes})()
    return a


def test_stream_sse_happy_path(client, monkeypatch):
    partials = [
        PartialResult(text="he", committed="", partial="he"),
        PartialResult(text="hello world", committed="hello world", partial="", is_final=True),
    ]
    monkeypatch.setattr(server.registry, "make_adapter",
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
    meta = AdapterMeta(
        id="stub/echo", provider="stub-serve", vendor="stub", name="Stub",
        source="cloud", modes=["batch"], langs=["en"])
    monkeypatch.setattr(server.registry, "resolve", lambda model: meta)
    monkeypatch.setattr(server.registry, "make_adapter",
                        lambda model: pytest.fail("mode mismatch must not create adapter"))
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "stub/echo", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 400
    assert "not a streaming model" in r.json()["error"]["message"]


def test_stream_unknown_model_404(client, monkeypatch):
    def boom(model):
        raise server.registry.ModelNotFoundError("nope")
    monkeypatch.setattr(server.registry, "resolve", boom)
    monkeypatch.setattr(server.registry, "make_adapter",
                        lambda model: pytest.fail("unknown model must not create adapter"))
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "does/not-exist", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 404


def test_stream_setup_broad_exception_500(client, monkeypatch):
    def boom(model):
        raise RuntimeError("plugin load failed")
    monkeypatch.setattr(server.registry, "make_adapter", boom)
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "stub/echo", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 500


def test_stream_error_event(client, monkeypatch):
    partials = [PartialResult(text="", is_final=True, error="boom")]
    monkeypatch.setattr(server.registry, "make_adapter",
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
    monkeypatch.setattr(server.registry, "make_adapter",
                        lambda model: _fake_adapter(["streaming"], partials))
    r = client.post("/v1/audio/transcriptions",
                    data={"model": "stub/echo", "stream": "true"},
                    files={"file": ("a.wav", b"placeholder", "audio/wav")})
    assert r.status_code == 200
    body = r.text
    assert '"type": "transcript.text.done"' in body
    assert '"text": "xy"' in body
    assert "data: [DONE]" in body
