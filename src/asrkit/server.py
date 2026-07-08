"""`asrkit serve` —— OpenAI 兼容的本地转写服务（LiteLLM proxy 那一半）。

暴露 `POST /v1/audio/transcriptions`、`GET /v1/models`、`GET /health`。
任何 OpenAI 客户端改 base_url 即可调用 ASRKit 背后的全部端云模型。

fastapi/uvicorn 走可选 extra（`pip install "asrkit[serve]"`）；本模块顶层不 import 它们，
故基础安装导入本模块不崩，仅在真正 build_app/serve 时才需要。透明原则：上传原始字节落临时文件。

注意：本模块**不**用 `from __future__ import annotations`——FastAPI 需要端点参数的真实运行时类型
（stringized 注解会让 UploadFile/Form 解析失败）。
"""
import json as _json
import os
import tempfile
import threading
from collections import OrderedDict

from . import api, formats, log, registry
from .types import AudioInput, TranscribeOptions

_LOG = log.get_logger("serve")


def _sse_event(obj) -> str:
    return f"data: {_json.dumps(obj)}\n\n"


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass

# 已加载 adapter 的有界 LRU 缓存,避免每请求重载本地模型 + 防长跑内存无界。
# 单进程内存缓存;同模型并发首次可能各建一次(在锁外 make),重入锁后收敛为一个。
_ADAPTERS: "OrderedDict[str, object]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _cache_size() -> int:
    """serve adapter LRU 容量。env ASRKIT_SERVE_CACHE 覆盖,非法/<=0 回退默认 8。"""
    raw = os.environ.get("ASRKIT_SERVE_CACHE")
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return 8


def _get_adapter(model: str):
    with _CACHE_LOCK:
        a = _ADAPTERS.get(model)
        if a is not None:
            _ADAPTERS.move_to_end(model)
            return a
    a = registry.make_adapter(model)         # 锁外(可能慢/可能抛 ModelNotFoundError)
    with _CACHE_LOCK:
        existing = _ADAPTERS.get(model)      # 重入锁后再查,防并发双建覆盖热 adapter
        if existing is not None:
            _ADAPTERS.move_to_end(model)
            return existing
        _ADAPTERS[model] = a
        _ADAPTERS.move_to_end(model)
        while len(_ADAPTERS) > _cache_size():
            _ADAPTERS.popitem(last=False)
    return a


def _missing_deps_msg() -> str:
    return ('serve needs extra deps. Run: pip install "asrkit[serve]"')


def build_app():
    """构造并返回 FastAPI app（延迟 import；缺依赖抛友好 RuntimeError）。"""
    try:
        from fastapi import FastAPI, File, Form, UploadFile
        from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
        from starlette.concurrency import run_in_threadpool, iterate_in_threadpool
    except ImportError as e:
        raise RuntimeError(_missing_deps_msg()) from e

    app = FastAPI(title="ASRKit", description="OpenAI-compatible speech-to-text")

    class _CleanupStreamingResponse(StreamingResponse):
        """__call__ 的 finally 保证执行：断连时 Starlette 抛 ClientDisconnect，
        仍能 aclose 上游迭代器 + 清理 tmp（生成器自身 finally 在断连时不保证跑）。"""
        def __init__(self, *args, cleanup_path=None, **kw):
            super().__init__(*args, **kw)
            self._cleanup_path = cleanup_path

        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                try:
                    await self.body_iterator.aclose()     # 停上游 sherpa 迭代
                except Exception:  # noqa: BLE001
                    pass
                if self._cleanup_path:
                    _unlink(self._cleanup_path)

    def _stream_transcription(model, path, language):
        try:
            adapter = _get_adapter(model)          # 复用 serve LRU 缓存
            if "streaming" not in adapter.meta.modes:
                _unlink(path)
                return JSONResponse(status_code=400,
                                    content={"error": {"message": f"{model} is not a streaming model"}})
        except registry.ModelNotFoundError as e:
            _unlink(path)
            return JSONResponse(status_code=404, content={"error": {"message": str(e)}})
        except Exception:  # noqa: BLE001 — 早错兜底，防 tmp 泄露
            _unlink(path)
            _LOG.exception("stream setup error: model=%s", model)
            return JSONResponse(status_code=500, content={"error": {"message": "internal server error"}})
        opts = TranscribeOptions(lang_hint=language)
        from .audio import AudioFormatError, iter_file_chunks

        async def _sse():
            sent = ""                              # 已发送的 committed 前缀
            try:
                chunks = iter_file_chunks(path, 16000, 1, 0.1, convert=opts.convert)
                gen = adapter.transcribe_stream(chunks, opts)
                async for pr in iterate_in_threadpool(gen):
                    if pr.error:
                        yield _sse_event({"type": "error", "error": pr.error})
                        break
                    full = pr.text if pr.is_final else pr.committed   # append-only 源
                    if full.startswith(sent) and len(full) > len(sent):   # 防御非追加
                        yield _sse_event({"type": "transcript.text.delta", "delta": full[len(sent):]})
                        sent = full
                    if pr.is_final:
                        yield _sse_event({"type": "transcript.text.done", "text": pr.text})
                yield "data: [DONE]\n\n"
            except AudioFormatError as e:
                yield _sse_event({"type": "error", "error": str(e)})
                yield "data: [DONE]\n\n"
            except Exception:  # noqa: BLE001
                _LOG.exception("stream transcription error: model=%s", model)
                yield _sse_event({"type": "error", "error": "internal server error"})
                yield "data: [DONE]\n\n"
            # 不在此 unlink：交给 _CleanupStreamingResponse.__call__ 的 finally（断连也保证）

        _LOG.info("stream transcribe model=%s start", model)
        return _CleanupStreamingResponse(_sse(), media_type="text/event-stream", cleanup_path=path)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/models")
    def list_models():
        data = [{"id": m.id, "object": "model", "owned_by": m.vendor}
                for m in api.list_models()]
        return {"object": "list", "data": data}

    @app.post("/v1/audio/transcriptions")
    async def transcriptions(
        file: UploadFile = File(...),
        model: str = Form(...),
        language: str = Form(None),
        response_format: str = Form("json"),
        stream: bool = Form(False),
    ):
        # 透明：原始字节原样落临时文件，不解码
        suffix = os.path.splitext(file.filename or "")[1] or ".wav"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:                                          # 写盘加保护，失败即清理 + 500
            tmp.write(await file.read())
            tmp.close()
        except Exception:  # noqa: BLE001
            try:
                tmp.close()
            except Exception:
                pass
            _unlink(tmp.name)
            _LOG.exception("upload write error: model=%s", model)
            return JSONResponse(status_code=500, content={"error": {"message": "internal server error"}})

        if stream:
            return _stream_transcription(model, tmp.name, language)

        # —— 非流式：现状逻辑不变 ——
        try:
            try:
                adapter = _get_adapter(model)
            except registry.ModelNotFoundError as e:
                return JSONResponse(status_code=404, content={"error": {"message": str(e)}})
            opts = TranscribeOptions(lang_hint=language)
            # 同步推理放线程池，避免卡死 uvicorn 事件循环（否则 /health 也会挂）
            result = await run_in_threadpool(
                adapter.transcribe, AudioInput(original_path=tmp.name), opts)
        except Exception:  # noqa: BLE001 — 服务边界：细节记服务端，客户端只给通用信息
            _LOG.exception("transcription error: model=%s", model)
            return JSONResponse(status_code=500,
                                content={"error": {"message": "internal server error"}})
        finally:
            _unlink(tmp.name)               # tmp 已 close，直接清理

        if result.error:
            return JSONResponse(status_code=400, content={"error": {"message": result.error}})

        _LOG.info("transcribe model=%s fmt=%s ok", model, response_format)
        rf = (response_format or "json").lower()
        try:
            if rf in ("json",):
                return JSONResponse({"text": result.text})
            if rf == "verbose_json":
                return JSONResponse(_json.loads(formats.render(result, "json")))
            if rf == "text":
                return PlainTextResponse(result.text)
            if rf in ("srt", "vtt"):
                return PlainTextResponse(formats.render(result, rf))
        except formats.FormatError as e:
            return JSONResponse(status_code=400, content={"error": {"message": str(e)}})
        return JSONResponse(status_code=400,
                            content={"error": {"message": f"unknown response_format '{rf}'"}})

    return app


def serve(host: str = "127.0.0.1", port: int = 11435) -> None:
    """起服务（阻塞）。缺依赖抛友好 RuntimeError。"""
    log.ensure_configured()          # 确保直接调 serve() 也能见到 WARNING/ERROR
    try:
        import uvicorn
    except ImportError as e:
        raise RuntimeError(_missing_deps_msg()) from e
    app = build_app()
    uvicorn.run(app, host=host, port=port)
