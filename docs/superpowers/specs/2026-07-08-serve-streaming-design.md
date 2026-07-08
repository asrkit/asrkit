# 设计 — serve 流式端点(SSE)(P3-D)

> 状态:brainstorming 完成、用户批准、**Codex(gpt-5.5)评审采纳 4 项 → v2**,待实现计划。
>
> **v2 修订**(Codex,已复现的真问题):
> 1. **断连不泄露 tmp**:Starlette 断连时从 `send()` 抛 `ClientDisconnect`,**不跑** `_sse()` 的 `finally` → tmp 泄露(Codex 复现)。→ 用 `StreamingResponse` 子类,`__call__` 的 `finally` 里 `aclose()` 迭代器 + `_unlink`(**保证执行**);cleanup 移出 `_sse`。
> 2. **tmp.write 加保护**:写盘提到 try 外会在 read/write 失败时泄露 fd/文件、丢 500 形状。→ 写盘包 try,失败即清理 + 500。
> 3. **早错兜底**:`_get_adapter` 除 404/400 外的异常(registry/plugin/user-model 加载)会泄露 tmp。→ 加宽 except:log + unlink + 500。
> 4. **delta 防御**:切片前加 `full.startswith(sent)` 守卫(SherpaLocal 安全,但护住第三方 adapter 的非追加式 committed)。
>
> Codex 确认无误:`AudioFormatError` 经 `iterate_in_threadpool` 正确传播回 `_sse except`;`iterate_in_threadpool` 足以卸载重活到线程池。
> 定位约束:复用已有 `transcribe_stream`;serve 是 opt-in extra(fastapi);流式路径**复用 serve 的 adapter LRU 缓存**(与非流式路径一致,用 `_get_adapter`),不每请求重载模型。

---

## 1. 背景

serve 的 `POST /v1/audio/transcriptions` 现只做一次性 JSON。D 给它加 `stream=true` → **SSE**(`text/event-stream`),边转边推,让任意 OpenAI 客户端也能流式消费 asrkit 背后的端侧模型。这是"最小流式"故事的最后一块:文件(W4)、分段(E)、麦克风(C)、**HTTP 流式(D)**。

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 触发 | 现有端点加 `stream: bool = Form(False)`;`true` → SSE,`false` → 现状 JSON(不变) |
| D2 | 事件形态 | **OpenAI 兼容**:`transcript.text.delta`(`delta`=已定稿 committed 的追加部分,append-only)+ 末 `transcript.text.done`(`text`=全文)+ `data: [DONE]` |
| D3 | 异步 | 同步阻塞 `transcribe_stream` 用 `starlette.concurrency.iterate_in_threadpool` 包成异步,不卡事件循环 |
| D4 | 缓存 | 流式也走 `_get_adapter`(serve LRU),与非流式一致;`adapter.transcribe_stream(iter_file_chunks(...))` |
| D5 | 错误 | 非流式模型/未配置 → 400;未知模型 → 404;`AudioFormatError`/运行时 → 发 `{"type":"error",...}` 事件 + `[DONE]` |
| D6 | 临时文件 | SSE 生成器 `finally` 清理(流式路径独占 tmp 生命周期) |
| D7 | 不做 | WebSocket、麦克风经 serve、多路复用、鉴权 |

## 3. 设计(`server.py`,均在 `build_app()` 内)

### 3.1 imports 补
```python
        from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
        from starlette.concurrency import run_in_threadpool, iterate_in_threadpool
```

### 3.2 模块级小工具(文件顶部)
```python
def _sse_event(obj) -> str:
    return f"data: {_json.dumps(obj)}\n\n"


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
```

### 3.3 端点加 `stream` 参 + 分支

`transcriptions` 签名加 `stream: bool = Form(False)`。把 tmp 落盘提到 try 外,写完**先判 stream**:

```python
    @app.post("/v1/audio/transcriptions")
    async def transcriptions(
        file: UploadFile = File(...),
        model: str = Form(...),
        language: str = Form(None),
        response_format: str = Form("json"),
        stream: bool = Form(False),
    ):
        suffix = os.path.splitext(file.filename or "")[1] or ".wav"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:                                          # v2:写盘加保护,失败即清理 + 500
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
        # —— 非流式:现状逻辑不变 ——(原 try/except/finally 保持)
        try:
            try:
                adapter = _get_adapter(model)
            except registry.ModelNotFoundError as e:
                return JSONResponse(status_code=404, content={"error": {"message": str(e)}})
            opts = TranscribeOptions(lang_hint=language)
            result = await run_in_threadpool(
                adapter.transcribe, AudioInput(original_path=tmp.name), opts)
        except Exception:  # noqa: BLE001
            _LOG.exception("transcription error: model=%s", model)
            return JSONResponse(status_code=500, content={"error": {"message": "internal server error"}})
        finally:
            _unlink(tmp.name)
        ... (原 result.error / 格式渲染分支不变)
```

（把原非流式 `finally` 里的 `tmp.close()`+unlink 简化为 `_unlink(tmp.name)`;tmp 已 close。)

### 3.4 `_stream_transcription`(build_app 内,SSE)

先在 `build_app()` 内(fastapi import 之后)定义**带清理的响应子类**,保证断连也 unlink:

```python
        class _CleanupStreamingResponse(StreamingResponse):
            """__call__ 的 finally 保证执行:断连时 Starlette 抛 ClientDisconnect,
            仍能 aclose 上游迭代器 + 清理 tmp(生成器自身 finally 在断连时不保证跑)。"""
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
```

```python
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
        except Exception:                          # v2:早错兜底,防 tmp 泄露
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
                    if full.startswith(sent) and len(full) > len(sent):   # v2:防御非追加
                        yield _sse_event({"type": "transcript.text.delta", "delta": full[len(sent):]})
                        sent = full
                    if pr.is_final:
                        yield _sse_event({"type": "transcript.text.done", "text": pr.text})
                yield "data: [DONE]\n\n"
            except AudioFormatError as e:
                yield _sse_event({"type": "error", "error": str(e)})
                yield "data: [DONE]\n\n"
            except Exception:                       # noqa: BLE001
                _LOG.exception("stream transcription error: model=%s", model)
                yield _sse_event({"type": "error", "error": "internal server error"})
                yield "data: [DONE]\n\n"
            # 不在此 unlink:交给 _CleanupStreamingResponse.__call__ 的 finally(断连也保证)

        _LOG.info("stream transcribe model=%s start", model)
        return _CleanupStreamingResponse(_sse(), media_type="text/event-stream", cleanup_path=path)
```

- **delta 源 append-only**:非终态用 `committed`(端点定稿、只增),终态用 `pr.text`(=committed 全文)。`sent` 追踪已发前缀,只发增量;`full.startswith(sent)` 守住第三方 adapter 的非追加式 committed。未定稿的 volatile `partial` 不单独推(避免 OpenAI 客户端遇到"回退")。
- **临时文件**:进 SSE 前的 404/400/500 早返回各自 `_unlink`;进 SSE 后由 `_CleanupStreamingResponse.__call__` 的 `finally` 保证清理(**含断连**)。
- **缓存一致**:与非流式同走 `_get_adapter`,不每请求重载本地模型。

## 4. 契约/行为影响

- 纯增量:`stream=false`(默认)行为**逐字不变**;新增仅 `stream=true` 分支 + 两个模块级 helper。
- 无新依赖(fastapi/starlette 已是 serve extra)。

## 5. 改动清单

| 文件 | 改动 |
|---|---|
| `src/asrkit/server.py` | `_sse_event`/`_unlink` helper;端点加 `stream` 参 + `_stream_transcription`;imports 补 StreamingResponse/iterate_in_threadpool |
| `tests/test_serve.py` | 新增 SSE 测试 |
| `docs/usage.md` / `CHANGELOG.md` | serve 流式用法 + `[Unreleased]` |

## 6. 测试(FastAPI TestClient;mock `_get_adapter`)

- **SSE 正常流**:`monkeypatch server._get_adapter`→假 adapter(`.meta.modes=["streaming"]`;`.transcribe_stream(chunks,opts)` 忽略 chunks,yield 脚本化 PartialResult:committed 逐步增长 "he"→"hello",末尾 is_final text="hello world");POST `stream=true`;断言 `Content-Type: text/event-stream`、body 含 `transcript.text.delta`(delta 拼起来 = 全文)、末 `transcript.text.done` 带 `text`、`data: [DONE]`。
  - (假 transcribe_stream 不迭代 chunks → 不触发 load_samples,上传字节可为占位。)
- **非流式模型 + stream=true → 400**:假 adapter `.meta.modes=["batch"]`;断言 400 + "not a streaming model";tmp 被清理(不易直接断言,至少不泄露异常)。
- **未知模型 + stream=true → 404**:`_get_adapter` 抛 `ModelNotFoundError`。
- **stream=false 回归**:现有非流式 JSON 测试仍绿(不受影响)。
- **错误事件**:假 transcribe_stream yield 一个 `PartialResult(error=...)` → 断言 body 有 `{"type":"error"}` + `[DONE]`。
- **setup 广异常 → 500(v2)**:`monkeypatch _get_adapter` 抛非 ModelNotFoundError 的 `RuntimeError` → 断言 500 + 通用 message(tmp 不泄露——至少不抛未捕获)。
- **delta 防御(v2)**:假 adapter 的 committed **非追加**(如 "ab" 后变 "xy")→ 断言不产生错乱 delta(要么跳过、要么最终 done 带全文),不崩。
- **回归**:现有 serve 测试(health/models/非流式/缓存)全绿。
- **注**:客户端断连时的 tmp 清理由 `_CleanupStreamingResponse.__call__` 的 finally 保证——TestClient 不易模拟中途断连,此路径靠设计(响应级 finally)覆盖,不强求单测;正常完成/错误路径由上面用例覆盖。

## 7. 不做(YAGNI)

WebSocket、serve 麦克风、SSE 心跳/重连、鉴权、多模型并发编排。

## 8. 风险

- `iterate_in_threadpool` 每 `next()` 占一个线程池线程;单流可控,高并发多流吃线程——超出最小流式范围(文档注明)。
- delta 仅由 committed(端点)驱动:无端点的短音频要到最终 flush 才出一个大 delta——正确但不够"实时";实时性依赖端点检测(E)质量。
- `stream: bool = Form(False)` 的解析:FastAPI 认 "true"/"false"/"1"/"0";异常值按 422(FastAPI 校验)——可接受。
