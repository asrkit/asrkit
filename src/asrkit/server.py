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
import sys
import tempfile

from . import api, formats, registry
from .types import AudioInput, TranscribeOptions

# 已加载 adapter 按 model id 缓存，避免每请求重载本地模型（serve 关键）。
# 单进程内存缓存；同模型并发首次可能各建一次，无害。
_ADAPTERS: dict = {}


def _get_adapter(model: str):
    a = _ADAPTERS.get(model)
    if a is None:
        a = registry.make_adapter(model)   # 可能抛 ModelNotFoundError
        _ADAPTERS[model] = a
    return a


def _missing_deps_msg() -> str:
    return ('serve needs extra deps. Run: pip install "asrkit[serve]"')


def build_app():
    """构造并返回 FastAPI app（延迟 import；缺依赖抛友好 RuntimeError）。"""
    try:
        from fastapi import FastAPI, File, Form, UploadFile
        from fastapi.responses import JSONResponse, PlainTextResponse
        from starlette.concurrency import run_in_threadpool
    except ImportError as e:
        raise RuntimeError(_missing_deps_msg()) from e

    app = FastAPI(title="ASRKit", description="OpenAI-compatible speech-to-text")

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
    ):
        # 透明：原始字节原样落临时文件，不解码
        suffix = os.path.splitext(file.filename or "")[1] or ".wav"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(await file.read())
            tmp.close()
            try:
                adapter = _get_adapter(model)
            except registry.ModelNotFoundError as e:
                return JSONResponse(status_code=404, content={"error": {"message": str(e)}})
            opts = TranscribeOptions(lang_hint=language)
            # 同步推理放线程池，避免卡死 uvicorn 事件循环（否则 /health 也会挂）
            result = await run_in_threadpool(
                adapter.transcribe, AudioInput(original_path=tmp.name), opts)
        except Exception as e:  # noqa: BLE001 — 服务边界：细节记服务端，客户端只给通用信息
            print(f"[serve] transcription error: {type(e).__name__}: {e}", file=sys.stderr)
            return JSONResponse(status_code=500,
                                content={"error": {"message": "internal server error"}})
        finally:
            try:
                tmp.close()               # 若上面 read/write 抛异常，这里兜底关 fd
            except Exception:
                pass
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        if result.error:
            return JSONResponse(status_code=400, content={"error": {"message": result.error}})

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
    try:
        import uvicorn
    except ImportError as e:
        raise RuntimeError(_missing_deps_msg()) from e
    app = build_app()
    uvicorn.run(app, host=host, port=port)
