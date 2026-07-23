"""`asrkit serve` —— OpenAI 兼容的本地转写服务。

暴露 `POST /v1/audio/transcriptions`、`GET /v1/models`、`GET /health`。
fastapi/uvicorn 是可选 extra；本模块顶层不导入它们，基础安装仍可正常 import。

注意：本模块不使用 `from __future__ import annotations`。FastAPI 需要端点参数的
真实运行时类型，stringized 注解会破坏 UploadFile/Form 解析。
"""
import asyncio
import json as _json
import os
import queue
import secrets
import tempfile
import threading
from concurrent.futures import Executor, Future, TimeoutError as FutureTimeoutError
from contextlib import asynccontextmanager

from . import api, formats, log, registry
from ._adapter_manager import _AdapterManager
from .daemon.security import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_UPLOAD_MB,
    DEFAULT_REQUEST_TIMEOUT_S,
)
from .types import AudioInput, TranscribeOptions

_LOG = log.get_logger("serve")
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_MULTIPART_OVERHEAD_BYTES = 1024 * 1024
_STREAM_QUEUE_SIZE = 16
_ADAPTER_SHUTDOWN_TIMEOUT_S = 1.0
_TRANSCRIPTION_PATH = "/v1/audio/transcriptions"


def _sse_event(obj) -> str:
    return f"data: {_json.dumps(obj)}\n\n"


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


class _UploadTooLarge(Exception):
    pass


class _WireBodyTooLarge(Exception):
    """multipart parser 前的 wire body 超限信号。"""


class _RequestLimiter:
    """立即拒绝超额请求；不建立无界等待队列。"""

    def __init__(self, limit):
        self._limit = limit
        self._active = 0
        self._lock = threading.Lock()

    async def try_acquire(self):
        if self._limit is None:
            return True
        with self._lock:
            if self._active >= self._limit:
                return False
            self._active += 1
            return True

    def release(self):
        if self._limit is None:
            return
        # Future callback 可能来自 worker thread；不使用非线程安全 asyncio primitive。
        with self._lock:
            if self._active > 0:
                self._active -= 1


class _RequestPermit:
    """请求 permit；response 与不可取消 worker 都结束后才幂等释放。"""

    def __init__(self, limiter):
        self._limiter = limiter
        self._lock = threading.Lock()
        self._pins = 0
        self._response_finished = False
        self._released = False

    def pin(self, future):
        with self._lock:
            if self._released:
                raise RuntimeError("request permit has already been released")
            self._pins += 1
        future.add_done_callback(self._unpin)

    def _unpin(self, _future):
        release = False
        with self._lock:
            self._pins -= 1
            release = self._claim_release_locked()
        if release:
            self._limiter.release()

    def _claim_release_locked(self):
        if self._response_finished and self._pins == 0 and not self._released:
            self._released = True
            return True
        return False

    def release_once(self):
        """标记 ASGI response 已结束；若有 worker pin 则延迟到 Future 完成。"""
        release = False
        with self._lock:
            self._response_finished = True
            release = self._claim_release_locked()
        if release:
            self._limiter.release()

    finish_response = release_once


class _DaemonExecutor(Executor):
    """最小化 daemon worker pool，使不可取消的 native 调用不拖死进程退出。"""

    _STOP = object()

    def __init__(self, max_workers, *, thread_name_prefix):
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._threads = []
        self._shutdown = False
        self._stop_sent = False

    def submit(self, fn, /, *args, **kwargs):
        with self._lock:
            if self._shutdown:
                raise RuntimeError("cannot schedule new futures after shutdown")
            future = Future()
            self._queue.put((future, fn, args, kwargs))
            if len(self._threads) < self._max_workers:
                thread = threading.Thread(
                    target=self._worker,
                    name=f"{self._thread_name_prefix}_{len(self._threads)}",
                    daemon=True,
                )
                self._threads.append(thread)
                thread.start()
            return future

    def _worker(self):
        while True:
            work = self._queue.get()
            if work is self._STOP:
                return
            future, fn, args, kwargs = work
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = fn(*args, **kwargs)
            except BaseException as error:
                future.set_exception(error)
            else:
                future.set_result(result)

    def shutdown(self, wait=True, *, cancel_futures=False):
        with self._lock:
            self._shutdown = True
            if cancel_futures:
                retained = []
                while True:
                    try:
                        work = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if work is self._STOP:
                        retained.append(work)
                    else:
                        work[0].cancel()
                for work in retained:
                    self._queue.put(work)
            if not self._stop_sent:
                self._stop_sent = True
                for _thread in self._threads:
                    self._queue.put(self._STOP)
            threads = list(self._threads)
        if wait:
            for thread in threads:
                thread.join()


def _route_path(scope):
    path = scope.get("path", "")
    root_path = (scope.get("root_path") or "").rstrip("/")
    # 兼容严格 ASGI（path 已去 root_path）和保留前缀的宿主实现。
    if root_path and path.startswith(root_path + "/"):
        return path[len(root_path):]
    return path


def _content_length(scope):
    values = []
    chunked = False
    for name, raw_value in scope.get("headers", []):
        lower_name = name.lower()
        if lower_name == b"content-length":
            try:
                text = raw_value.decode("ascii")
            except UnicodeDecodeError:
                return None, "invalid Content-Length header"
            values.extend(part.strip() for part in text.split(","))
        elif lower_name == b"transfer-encoding":
            try:
                codings = raw_value.decode("ascii").lower().split(",")
            except UnicodeDecodeError:
                return None, "invalid Transfer-Encoding header"
            chunked = chunked or any(coding.strip() == "chunked" for coding in codings)

    if not values:
        return None, None
    if chunked:
        return None, "Content-Length cannot be combined with chunked transfer encoding"
    if any(not value or not value.isdigit() for value in values):
        return None, "invalid Content-Length header"
    try:
        numbers = [int(value) for value in values]
    except ValueError:
        return None, "invalid Content-Length header"
    if any(number != numbers[0] for number in numbers[1:]):
        return None, "conflicting Content-Length headers"
    return numbers[0], None


async def _send_error(send, status, message, *, headers=None):
    body = _json.dumps({"error": {"message": message}}, separators=(",", ":")).encode()
    response_headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    response_headers.extend(headers or [])
    await send({"type": "http.response.start", "status": status,
                "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


class _EntryGateMiddleware:
    """认证、wire body 上限和 permit 的纯 ASGI 入口闸门。"""

    def __init__(self, app, *, auth_token, max_upload_bytes, limiter):
        self.app = app
        self.auth_token = auth_token
        self.limiter = limiter
        self.wire_limit = (None if max_upload_bytes is None else
                           max_upload_bytes + _MULTIPART_OVERHEAD_BYTES)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = _route_path(scope)
        if self.auth_token and path != "/health":
            authorization_values = [
                value for name, value in scope.get("headers", [])
                if name.lower() == b"authorization"
            ]
            authorization = (authorization_values[0]
                             if len(authorization_values) == 1 else b"")
            try:
                scheme, _, value = authorization.decode("latin-1").partition(" ")
            except Exception:
                scheme, value = "", ""
            if (scheme.lower() != "bearer"
                    or not secrets.compare_digest(value, self.auth_token)):
                await _send_error(
                    send, 401, "unauthorized",
                    headers=[(b"www-authenticate", b"Bearer")],
                )
                return

        if scope.get("method") != "POST" or path != _TRANSCRIPTION_PATH:
            await self.app(scope, receive, send)
            return

        # 普通命令行服务无默认 token；拒绝浏览器跨源 simple POST，防止
        # 恶意网页借 loopback 触发本地推理或云端计费。curl/SDK 不发 Origin。
        origins = [
            value.strip() for name, value in scope.get("headers", [])
            if name.lower() == b"origin"
        ]
        if any(origins):
            await _send_error(send, 403, "browser-origin requests are not allowed")
            return

        length, header_error = _content_length(scope)
        if header_error:
            await _send_error(send, 400, header_error)
            return
        if self.wire_limit is not None and length is not None and length > self.wire_limit:
            await _send_error(send, 413, "audio upload exceeds the configured limit")
            return
        if not await self.limiter.try_acquire():
            await _send_error(send, 429, "too many concurrent transcription requests")
            return

        permit = _RequestPermit(self.limiter)
        state = scope.get("state")
        if state is None:
            state = {}
            scope["state"] = state
        state["_asrkit_permit"] = permit
        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if self.wire_limit is not None and received > self.wire_limit:
                    raise _WireBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _WireBodyTooLarge:
            if response_started:
                raise
            await _send_error(send, 413, "audio upload exceeds the configured limit")
        finally:
            permit.finish_response()


def _cache_size() -> int:
    """serve adapter LRU 容量。env ASRKIT_SERVE_CACHE 覆盖，非法值回退 8。"""
    raw = os.environ.get("ASRKIT_SERVE_CACHE")
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return 8


def _missing_deps_msg() -> str:
    return 'serve needs extra deps. Run: pip install "asrkit[serve]"'


def _uvicorn_transport_options():
    """固定为项目实际使用的 HTTP/asyncio 栈，避免探测未声明加速器。"""
    return {"loop": "asyncio", "http": "h11", "ws": "none"}


def _acquire_configured(manager, model):
    lease = manager.lease(model)
    try:
        configured_hook = getattr(lease.adapter, "is_configured", None)
        configured = (lease.invoke("is_configured")
                      if callable(configured_hook) else True)
    except BaseException:
        lease.discard()
        raise
    if not configured:
        # 凭据可在运行期补齐；不得永久缓存“未配置”快照。
        lease.discard()
        return None
    return lease


def _defer_lease_release(lease, executor, *, discard=False):
    """从 event loop 路径移交 release/close，防止第三方 close hook 卡住 I/O。"""
    action = lease.discard if discard else lease.release
    try:
        executor.submit(action)
    except RuntimeError:
        # executor 已 shutdown 时仍要交还 lease；daemon 保持关闭有界。
        threading.Thread(
            target=action, name="asrkit-lease-release", daemon=True).start()


def _release_lease_result(future, executor):
    """请求在 adapter 构造期取消时，由 Future 收回后续产生的 lease。"""
    try:
        lease = future.result()
    except BaseException:
        return
    if lease is not None:
        _defer_lease_release(lease, executor)


def _run_batch(lease, audio, opts, path):
    try:
        return lease.invoke("transcribe", audio, opts)
    finally:
        try:
            _unlink(path)
        finally:
            lease.release()


def _consume_worker_exception(future):
    try:
        future.exception()
    except BaseException:
        pass


def _put_stream_message(loop, queue, message, stop):
    """有界地把 worker 结果送回 event loop；断连时不困在满队列。"""
    while not stop.is_set():
        try:
            pending = asyncio.run_coroutine_threadsafe(queue.put(message), loop)
        except RuntimeError:
            return False
        try:
            pending.result(timeout=0.1)
            return True
        except FutureTimeoutError:
            if not pending.cancel():
                try:
                    pending.result()
                    return True
                except BaseException:
                    return False
        except BaseException:
            return False
    return False


def _run_stream(lease, path, opts, model, loop, queue, stop):
    from .audio import AudioFormatError, iter_file_chunks

    stream = None
    try:
        chunks = iter_file_chunks(path, 16000, 1, 0.1, convert=opts.convert)
        stream = lease.iterate("transcribe_stream", chunks, opts)
        for partial_result in stream:
            if not _put_stream_message(loop, queue, ("result", partial_result), stop):
                return
            if partial_result.error:
                break
    except AudioFormatError as error:
        _put_stream_message(loop, queue, ("error", str(error)), stop)
    except Exception:  # noqa: BLE001 — 服务边界不向客户端泄露内部细节
        _LOG.exception("stream transcription error: model=%s", model)
        _put_stream_message(loop, queue, ("error", "internal server error"), stop)
    finally:
        _put_stream_message(loop, queue, ("done", None), stop)
        try:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        finally:
            try:
                _unlink(path)
            finally:
                lease.release()


def build_app(*, auth_token=None, max_upload_bytes=None, max_concurrency=None,
              request_timeout_s=None, temp_dir=None, health_info=None):
    """构造并返回 FastAPI app（延迟 import；缺依赖抛友好 RuntimeError）。"""
    if max_upload_bytes is not None and max_upload_bytes < 0:
        raise ValueError("max_upload_bytes must be non-negative or None")
    if max_concurrency is not None and max_concurrency <= 0:
        raise ValueError("max_concurrency must be positive or None")
    if request_timeout_s is not None and request_timeout_s < 0:
        raise ValueError("request_timeout_s must be non-negative or None")

    try:
        from fastapi import FastAPI, File, Form, Request, UploadFile
        from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
    except ImportError as error:
        raise RuntimeError(_missing_deps_msg()) from error

    limiter = _RequestLimiter(max_concurrency)
    manager = _AdapterManager(lambda model: registry.make_adapter(model), capacity=_cache_size())
    worker_count = max(4, min(max_concurrency or 32, 32))
    executor = _DaemonExecutor(
        max_workers=worker_count, thread_name_prefix="asrkit-serve")

    @asynccontextmanager
    async def _lifespan(_app):
        try:
            yield
        finally:
            # manager 自身做有界等待；超时的 active lease 由 worker 回调 close。
            manager.shutdown(timeout=_ADAPTER_SHUTDOWN_TIMEOUT_S)
            executor.shutdown(wait=False)

    app = FastAPI(
        title="ASRKit",
        description="OpenAI-compatible speech-to-text",
        lifespan=_lifespan,
    )
    app.state.adapter_manager = manager
    app.state.adapter_executor = executor
    app.add_middleware(
        _EntryGateMiddleware,
        auth_token=auth_token,
        max_upload_bytes=max_upload_bytes,
        limiter=limiter,
    )

    class _CleanupStreamingResponse(StreamingResponse):
        """无论正常结束还是 SSE 断连，都通知 worker 停止继续产生。"""

        def __init__(self, *args, on_close=None, **kwargs):
            super().__init__(*args, **kwargs)
            self._on_close = on_close

        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                if self._on_close:
                    self._on_close()
                try:
                    await self.body_iterator.aclose()
                except Exception:  # noqa: BLE001
                    pass

    @app.get("/health")
    def health():
        return {"status": "ok", **dict(health_info or {})}

    @app.get("/v1/models")
    def list_models():
        data = [{"id": meta.id, "object": "model", "owned_by": meta.vendor}
                for meta in api.list_models()]
        return {"object": "list", "data": data}

    @app.post(_TRANSCRIPTION_PATH)
    async def transcriptions(
        request: Request,
        file: UploadFile = File(...),
        model: str = Form(...),
        language: str = Form(None),
        response_format: str = Form("json"),
        stream: bool = Form(False),
    ):
        def error_response(status, message):
            return JSONResponse(status_code=status, content={"error": {"message": message}})

        response_kind = (response_format or "json").lower()
        allowed_formats = {"json", "verbose_json", "text", "srt", "vtt"}
        if response_kind not in allowed_formats:
            await file.close()
            return error_response(400, f"unknown response_format '{response_kind}'")
        if stream and response_kind != "json":
            await file.close()
            return error_response(400, "streaming only supports response_format 'json'")

        loop = asyncio.get_running_loop()
        permit = request.scope["state"]["_asrkit_permit"]
        resolve_future = loop.run_in_executor(executor, registry.resolve, model)
        permit.pin(resolve_future)
        try:
            meta = await asyncio.shield(resolve_future)
        except asyncio.CancelledError:
            await file.close()
            raise
        except registry.ModelNotFoundError as error:
            await file.close()
            return error_response(404, str(error))
        except Exception:  # noqa: BLE001
            await file.close()
            _LOG.exception("model resolution error: model=%s", model)
            return error_response(500, "internal server error")

        if stream and "streaming" not in meta.modes:
            await file.close()
            return error_response(400, f"{model} is not a streaming model")
        if not stream and "batch" not in meta.modes:
            await file.close()
            return error_response(400, f"{model} does not support batch transcription")
        if (response_kind in {"srt", "vtt"}
                and meta.capabilities.get("segment_timestamps") is not True):
            await file.close()
            return error_response(
                400, f"{model} does not declare segment timestamps required for '{response_kind}'")

        # alias 只是输入语法；缓存/single-flight 必须以 registry 解析后的权威 id 为键。
        lease_future = loop.run_in_executor(
            executor, _acquire_configured, manager, meta.id)
        permit.pin(lease_future)
        try:
            lease = await asyncio.shield(lease_future)
        except asyncio.CancelledError:
            lease_future.add_done_callback(
                lambda completed: _release_lease_result(completed, executor))
            await file.close()
            raise
        except registry.ModelNotFoundError as error:
            await file.close()
            return error_response(404, str(error))
        except Exception:  # noqa: BLE001
            await file.close()
            _LOG.exception("adapter setup error: model=%s", model)
            return error_response(500, "internal server error")

        if lease is None:
            await file.close()
            return error_response(
                400, f"{model} is not configured (missing API key?). See docs/usage.md")

        audio_path = None
        tmp = None
        upload_error = None
        filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        suffix = os.path.splitext(filename)[1]
        if not suffix or len(suffix) > 16:
            suffix = ".audio"
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir)
            audio_path = tmp.name
            written = 0
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if max_upload_bytes is not None and written > max_upload_bytes:
                    raise _UploadTooLarge
                tmp.write(chunk)
            tmp.close()
        except _UploadTooLarge:
            if tmp is not None:
                tmp.close()
            upload_error = error_response(
                413, "audio upload exceeds the configured limit")
        except asyncio.CancelledError:
            if tmp is not None:
                tmp.close()
            if audio_path:
                _unlink(audio_path)
            _defer_lease_release(lease, executor)
            raise
        except Exception:  # noqa: BLE001
            try:
                if tmp is not None:
                    tmp.close()
            except Exception:
                pass
            _LOG.exception("upload write error: model=%s", model)
            upload_error = error_response(500, "internal server error")
        finally:
            try:
                await file.close()
            except Exception:  # noqa: BLE001
                pass

        if upload_error is not None or audio_path is None:
            if audio_path:
                _unlink(audio_path)
            _defer_lease_release(lease, executor)
            return upload_error or error_response(500, "internal server error")

        opts = TranscribeOptions(lang_hint=language)
        if stream:
            queue: asyncio.Queue = asyncio.Queue(maxsize=_STREAM_QUEUE_SIZE)
            stop = threading.Event()
            try:
                worker = loop.run_in_executor(
                    executor, _run_stream, lease, audio_path, opts,
                    model, loop, queue, stop)
            except Exception:  # pragma: no cover - executor 提交失败的防线
                _defer_lease_release(lease, executor)
                _unlink(audio_path)
                _LOG.exception("stream worker submission error: model=%s", model)
                return error_response(500, "internal server error")
            permit.pin(worker)
            worker.add_done_callback(_consume_worker_exception)

            async def sse():
                sent = ""
                try:
                    while True:
                        kind, value = await queue.get()
                        if kind == "done":
                            yield "data: [DONE]\n\n"
                            return
                        if kind == "error":
                            yield _sse_event({"type": "error", "error": value})
                            continue
                        partial_result = value
                        if partial_result.error:
                            yield _sse_event(
                                {"type": "error", "error": partial_result.error})
                            continue
                        full = (partial_result.text if partial_result.is_final
                                else partial_result.committed)
                        if full.startswith(sent) and len(full) > len(sent):
                            yield _sse_event({
                                "type": "transcript.text.delta",
                                "delta": full[len(sent):],
                            })
                            sent = full
                        if partial_result.is_final:
                            yield _sse_event({
                                "type": "transcript.text.done",
                                "text": partial_result.text,
                            })
                finally:
                    stop.set()

            _LOG.info("stream transcribe model=%s start", model)
            return _CleanupStreamingResponse(
                sse(), media_type="text/event-stream", on_close=stop.set)

        audio = AudioInput(original_path=audio_path)
        try:
            worker = loop.run_in_executor(
                executor, _run_batch, lease, audio, opts, audio_path)
        except Exception:  # pragma: no cover - executor 提交失败的防线
            _defer_lease_release(lease, executor)
            _unlink(audio_path)
            _LOG.exception("batch worker submission error: model=%s", model)
            return error_response(500, "internal server error")
        permit.pin(worker)
        worker.add_done_callback(_consume_worker_exception)

        try:
            if request_timeout_s is None:
                result = await asyncio.shield(worker)
            else:
                result = await asyncio.wait_for(
                    asyncio.shield(worker), timeout=request_timeout_s)
        except asyncio.TimeoutError:
            return error_response(504, "transcription request timed out")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 服务边界只向客户端给通用错误
            _LOG.exception("transcription error: model=%s", model)
            return error_response(500, "internal server error")

        if result.error:
            return error_response(400, result.error)

        _LOG.info("transcribe model=%s fmt=%s ok", model, response_kind)
        try:
            if response_kind == "json":
                return JSONResponse({"text": result.text})
            if response_kind == "verbose_json":
                payload = _json.loads(formats.render(result, "json"))
                if "lang" in payload:
                    payload["language"] = payload.pop("lang")
                return JSONResponse(payload)
            if response_kind == "text":
                return PlainTextResponse(result.text)
            return PlainTextResponse(formats.render(result, response_kind))
        except formats.FormatError as error:
            return error_response(400, str(error))

    return app


def serve(host: str = "127.0.0.1", port: int = 11435,
          shutdown_timeout_s=None, **app_options) -> None:
    """起服务（阻塞）。缺依赖抛友好 RuntimeError。"""
    log.ensure_configured()
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError(_missing_deps_msg()) from error
    # 命令行和直接 serve() 都有安全上界；纯 build_app() 嵌入者可自行决定。
    app_options.setdefault("max_upload_bytes", DEFAULT_MAX_UPLOAD_MB * 1024 * 1024)
    app_options.setdefault("max_concurrency", DEFAULT_MAX_CONCURRENCY)
    app_options.setdefault("request_timeout_s", DEFAULT_REQUEST_TIMEOUT_S)
    app = build_app(**app_options)
    options = _uvicorn_transport_options()
    if shutdown_timeout_s is not None:
        options["timeout_graceful_shutdown"] = shutdown_timeout_s
    uvicorn.run(app, host=host, port=port, **options)
