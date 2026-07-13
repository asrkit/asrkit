# W3a 契约做实(segments + 选项诚实)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 whisper 家族 adapter 填 `TranscribeResult.segments`(srt/vtt 从 0% 可用变可用),并让被忽略的 `--language` 出声(warning)而非静默。

**Architecture:** 新 `capabilities.py`(三态 language_hint 归一 + 告警)接入 `api._run_adapter`;faster-whisper/whispercpp 直接填 segments,openai/whisper-1 能力位门控 verbose_json;`emit` 批量把 warnings 打到 stderr。零新运行时依赖。

**Tech Stack:** Python 3.9+;pytest + monkeypatch(sys.modules 假引擎)。

## Global Constraints

- 版本号**不动**(`__version__` 保持 `0.5.2`);发版由人类定。
- **零新增运行时依赖**;base 仍只 `requests`。
- 终端/报错**英文**;代码注释**中文**。
- **capabilities 用既有三态字符串**(`"required"/"supported"/"none"`),**绝不用真值判断**(`"none"` 是真值 —— 用真值会让 siliconflow 破例发 language)。归一只经 `capabilities.language_supported/language_ignored`。
- **云端请求只在能力位开启时才变**:只有 openai/whisper-1(显式 capabilities)请求 verbose_json/language;**siliconflow/telespeech 请求逐字不变**。
- 解析全程防御:无 segments → `segments=None`,text 照旧。
- 提交用 `git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com"`,**显式 `git add <文件>`**,不 push。
- **测试一律** `PYTHONPATH=src python -m pytest ... -o addopts=""`(miniconda 有旧副本会遮蔽)。
- 契约细节见历史 spec：[`../specs/2026-07-07-w3a-contract-fulfillment-design.md`](../specs/2026-07-07-w3a-contract-fulfillment-design.md)。

---

## File Structure

- **Create** `src/asrkit/capabilities.py` — `language_supported/language_ignored/warnings_for`。
- **Modify** `src/asrkit/api.py` — `_run_adapter` 接入 `warnings_for`。
- **Modify** `src/asrkit/adapters/models_local.py` — capabilities 按架构(whisper→language_hint supported;senseVoice→none)。
- **Modify** `local_faster_whisper.py` — 填 segments(物化进计时区)+ 模型 capabilities。
- **Modify** `local_whispercpp.py` — 填 segments(厘秒→秒)+ language + 模型 capabilities。
- **Modify** `cloud_openai.py` — 门控 verbose_json+language+解析 segments;whisper-1 meta capabilities。
- **Modify** `src/asrkit/emit.py` — 每条记录 warnings 打 stderr。
- **Create** `tests/test_capabilities.py`、`tests/test_segments.py`;**Modify** `tests/test_batch.py`(emit 告警)。
- **Modify** `docs/result-contract.md`、`CHANGELOG.md`。

---

## Task 1: `capabilities.py` + api 接线 + sherpa 能力位(选项诚实 end-to-end)

**Files:**
- Create: `src/asrkit/capabilities.py`
- Modify: `src/asrkit/api.py`, `src/asrkit/adapters/models_local.py`
- Test: `tests/test_capabilities.py`

**Interfaces:**
- Produces: `language_supported(meta)->bool`、`language_ignored(meta)->bool`、`warnings_for(opts, meta)->list`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_capabilities.py
from asrkit import api, capabilities, registry
from asrkit.types import AdapterMeta, BaseAdapter, TranscribeOptions, TranscribeResult


def _meta(lang):
    caps = {"language_hint": lang} if lang is not None else {}
    return AdapterMeta(id="x/y", provider="p", vendor="v", name="n",
                       source="cloud", modes=["batch"], langs=[], capabilities=caps)


def test_language_tristate():
    assert capabilities.language_supported(_meta("supported"))
    assert capabilities.language_supported(_meta("required"))
    assert not capabilities.language_supported(_meta("none"))
    assert not capabilities.language_supported(_meta(None))
    assert capabilities.language_ignored(_meta("none"))
    assert not capabilities.language_ignored(_meta("supported"))
    assert not capabilities.language_ignored(_meta(None))


def test_warnings_only_when_ignored_and_lang_passed():
    o = TranscribeOptions(lang_hint="zh")
    assert capabilities.warnings_for(o, _meta("none"))
    assert not capabilities.warnings_for(o, _meta("supported"))
    assert not capabilities.warnings_for(o, _meta(None))
    assert not capabilities.warnings_for(TranscribeOptions(), _meta("none"))   # 没传 lang


def test_sherpa_capabilities_by_arch():
    assert registry.resolve("local/sensevoice").capabilities.get("language_hint") == "none"
    assert registry.resolve("local/whisper-tiny").capabilities.get("language_hint") == "supported"
    # sherpa whisper 不标 segment_timestamps(不填 sherpa segments)
    assert "segment_timestamps" not in registry.resolve("local/whisper-tiny").capabilities


def test_api_appends_language_warning():
    @registry.register_protocol("stub-warn")
    class _Stub(BaseAdapter):
        def transcribe(self, audio, opts):
            return TranscribeResult(text="hi")
    registry.register_model(AdapterMeta(
        id="stub/warn", provider="stub-warn", vendor="stub", name="s",
        source="cloud", modes=["batch"], langs=[], capabilities={"language_hint": "none"}))
    r = api.transcribe("stub/warn", "a.wav", opts=TranscribeOptions(lang_hint="zh"))
    assert any("ignored" in w for w in (r.warnings or []))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_capabilities.py -o addopts="" -v`
Expected: FAIL(`ModuleNotFoundError: asrkit.capabilities`)

- [ ] **Step 3: 实现**

```python
# src/asrkit/capabilities.py
"""能力位(capabilities)判读:三态 language_hint 归一 + 选项诚实告警。

沿用 adapter-spec.md 的三态字符串约定,不引入 bool 混用:
  language_hint: "required" | "supported" | "none"
  segment_timestamps: True(模型返回 segments)
"""
from __future__ import annotations

_LANG_YES = ("supported", "required")
_LANG_NO = ("none",)


def language_supported(meta) -> bool:
    return (meta.capabilities or {}).get("language_hint") in _LANG_YES


def language_ignored(meta) -> bool:
    return (meta.capabilities or {}).get("language_hint") in _LANG_NO


def warnings_for(opts, meta) -> list:
    """仅对显式声明忽略 language 的模型、且用户传了 lang_hint 时告警;缺省/未知不告警。"""
    out = []
    if getattr(opts, "lang_hint", None) and language_ignored(meta):
        out.append(f"{meta.id} auto-detects language; --language is ignored")
    return out
```

`api.py` 的 `_run_adapter` 接线,把:
```python
    if isinstance(audio, str):
        audio = AudioInput(original_path=audio)   # 内核零处理：不解码，adapter 各取所需
    return adapter.transcribe(audio, opts or TranscribeOptions())
```
改为:
```python
    if isinstance(audio, str):
        audio = AudioInput(original_path=audio)   # 内核零处理：不解码，adapter 各取所需
    opts = opts or TranscribeOptions()
    result = adapter.transcribe(audio, opts)
    from . import capabilities
    w = capabilities.warnings_for(opts, adapter.meta)
    if w:
        result.warnings = (result.warnings or []) + w
    return result
```

`models_local.py` 的 `_metas()`,把 `capabilities={"max_input_duration_s": 30} if ctype == "whisper" else {}` 改为按架构计算(在循环体内、AdapterMeta 之前):
```python
        if ctype == "whisper":
            caps = {"max_input_duration_s": 30, "language_hint": "supported"}
        elif ctype == "senseVoice":
            caps = {"language_hint": "none"}
        else:
            caps = {}
```
并把 `AdapterMeta(...)` 里的 `capabilities=...` 参数改为 `capabilities=caps`。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_capabilities.py -o addopts="" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/capabilities.py src/asrkit/api.py src/asrkit/adapters/models_local.py tests/test_capabilities.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(capabilities): 三态 language_hint 归一 + 选项诚实告警;sherpa 按架构填能力位"
```

---

## Task 2: faster-whisper 填 segments

**Files:**
- Modify: `src/asrkit/adapters/local_faster_whisper.py`
- Test: `tests/test_segments.py`

**Interfaces:**
- Produces: faster-whisper 成功结果 `result.segments` 非空;模型 meta 带 `{"language_hint":"supported","segment_timestamps":True}`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_segments.py
import sys
import types

from asrkit import registry
from asrkit.types import AudioInput, TranscribeOptions


class _R:                       # 假 HTTP 响应(openai 测试用)
    def __init__(self, status=200, jsonobj=None):
        self.status_code = status
        self._j = jsonobj or {}
        self.text = ""
    def json(self):
        return self._j


def test_faster_whisper_fills_segments_and_materializes(monkeypatch):
    from asrkit.adapters import local_faster_whisper as fw

    class _Seg:
        def __init__(self, start, end, text):
            self.start, self.end, self.text = start, end, text

    class _Info:
        language = "en"

    class _Model:
        def __init__(self, *a, **k):
            pass
        def transcribe(self, path, language=None):
            gen = (s for s in [_Seg(0.0, 1.0, " hi"), _Seg(1.0, 2.0, " there")])  # 生成器
            return gen, _Info()

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _Model
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.setattr(fw, "_available", lambda: True)

    a = registry.make_adapter("faster-whisper/tiny")
    r = a.transcribe(AudioInput(original_path="x.wav"), TranscribeOptions())
    assert r.text == "hi there"                        # 物化后 text 不丢
    assert r.segments and len(r.segments) == 2
    assert r.segments[0].start == 0.0 and r.segments[0].text == "hi"


def test_faster_whisper_meta_capabilities():
    m = registry.resolve("faster-whisper/tiny")
    assert m.capabilities.get("segment_timestamps") is True
    assert m.capabilities.get("language_hint") == "supported"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_segments.py -k faster_whisper -o addopts="" -v`
Expected: FAIL(segments 为 None / capabilities 缺)

- [ ] **Step 3: 实现**

`local_faster_whisper.py`:import 加 `Segment`(`from ..types import AdapterMeta, AudioInput, BaseAdapter, Segment, TranscribeOptions, TranscribeResult`)。transcribe 里把:
```python
            t1 = time.perf_counter()
            segments, info = self._model.transcribe(
                audio.original_path, language=opts.lang_hint or None)
            text = "".join(s.text for s in segments).strip()
            decode_ms = int((time.perf_counter() - t1) * 1000)
            return TranscribeResult(
                text=text, lang=getattr(info, "language", None),
                latency_ms=load_ms + decode_ms,
                metrics={"load_ms": load_ms, "decode_ms": decode_ms})
```
改为:
```python
            t1 = time.perf_counter()
            segments, info = self._model.transcribe(
                audio.original_path, language=opts.lang_hint or None)
            seg_list = list(segments)                  # 物化:生成器单次消耗,真正解码在此
            decode_ms = int((time.perf_counter() - t1) * 1000)
            text = "".join(s.text for s in seg_list).strip()
            segs = [Segment(s.start, s.end, s.text.strip()) for s in seg_list] or None
            return TranscribeResult(
                text=text, segments=segs, lang=getattr(info, "language", None),
                latency_ms=load_ms + decode_ms,
                metrics={"load_ms": load_ms, "decode_ms": decode_ms})
```
模型注册加 capabilities:把 `register_models([AdapterMeta(id=f"faster-whisper/{name}", ... model=name)` 那条里加 `capabilities={"language_hint": "supported", "segment_timestamps": True},`。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_segments.py -k faster_whisper -o addopts="" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/adapters/local_faster_whisper.py tests/test_segments.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(faster-whisper): 填 segments(物化生成器进计时区)+ 能力位"
```

---

## Task 3: whispercpp 填 segments + 透传 language

**Files:**
- Modify: `src/asrkit/adapters/local_whispercpp.py`
- Test: `tests/test_segments.py`

**Interfaces:**
- Produces: whispercpp 成功结果 `result.segments`(t0/t1 厘秒→秒);transcribe 收到 `language=`;meta 带能力位。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_segments.py`)**

```python
def test_whispercpp_fills_segments_centiseconds_and_language(monkeypatch):
    from asrkit.adapters import local_whispercpp as wc

    seen = {}

    class _Seg:
        def __init__(self, t0, t1, text):
            self.t0, self.t1, self.text = t0, t1, text

    class _Model:
        def __init__(self, *a, **k):
            pass
        def transcribe(self, samples, language=None):
            seen["language"] = language
            return [_Seg(150, 320, " hello")]          # 厘秒:1.5s, 3.2s

    fake_mod = types.ModuleType("pywhispercpp.model")
    fake_mod.Model = _Model
    fake_pkg = types.ModuleType("pywhispercpp")
    monkeypatch.setitem(sys.modules, "pywhispercpp", fake_pkg)
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", fake_mod)
    monkeypatch.setattr(wc, "_available", lambda: True)
    monkeypatch.setattr(wc, "load_samples", lambda *a, **k: ([0.0], 16000))

    a = registry.make_adapter("whispercpp/tiny")
    r = a.transcribe(AudioInput(original_path="x.wav"), TranscribeOptions(lang_hint="en"))
    assert r.text == "hello"
    assert r.segments and r.segments[0].start == 1.5 and r.segments[0].end == 3.2   # 厘秒/100
    assert seen["language"] == "en"                    # language 透传(不再静默丢)


def test_whispercpp_meta_capabilities():
    m = registry.resolve("whispercpp/tiny")
    assert m.capabilities.get("segment_timestamps") is True
    assert m.capabilities.get("language_hint") == "supported"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_segments.py -k whispercpp -o addopts="" -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`local_whispercpp.py`:import 加 `Segment`。transcribe 里把:
```python
            t1 = time.perf_counter()
            segs = self._model.transcribe(samples)
            text = " ".join(getattr(s, "text", "") for s in segs).strip()
            decode_ms = int((time.perf_counter() - t1) * 1000)
            return TranscribeResult(
                text=text, latency_ms=load_ms + decode_ms,
                metrics={"load_ms": load_ms, "decode_ms": decode_ms})
```
改为(直接属性,不 `getattr(...,0)` 掩盖 binding 变化;显式中性 language 防 pywhispercpp 参数持久化):
```python
            t1 = time.perf_counter()
            segs_raw = self._model.transcribe(samples, language=opts.lang_hint or "auto")
            out = [Segment(s.t0 / 100.0, s.t1 / 100.0, s.text.strip()) for s in segs_raw]  # t0/t1 厘秒
            text = " ".join(x.text for x in out).strip()
            decode_ms = int((time.perf_counter() - t1) * 1000)
            return TranscribeResult(
                text=text, segments=out or None, latency_ms=load_ms + decode_ms,
                metrics={"load_ms": load_ms, "decode_ms": decode_ms})
```
> 注:pywhispercpp `Model.transcribe` 接受 `language=`(Codex 已核);中性值以 pywhispercpp 实际接受为准(`"auto"` 触发自动检测)。若 binding 无 `t0/t1` → `AttributeError` 进外层 `except` → `result.error`(不静默出全零)。

模型注册加 capabilities:`register_models([AdapterMeta(id=f"whispercpp/{name}", ... model=name)` 那条加 `capabilities={"language_hint": "supported", "segment_timestamps": True},`。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_segments.py -k whispercpp -o addopts="" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/adapters/local_whispercpp.py tests/test_segments.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(whispercpp): 填 segments(厘秒→秒,直接属性)+ 透传 language + 能力位"
```

---

## Task 4: openai 门控 verbose_json + language + 解析 segments

**Files:**
- Modify: `src/asrkit/adapters/cloud_openai.py`
- Test: `tests/test_segments.py`

**Interfaces:**
- Consumes: `capabilities.language_supported`(Task 1)、`_http.post`。
- Produces: openai/whisper-1 请求 verbose_json + `timestamp_granularities[]=segment` + language(有 hint 时),解析 segments;siliconflow 请求逐字不变。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_segments.py`)**

```python
def test_openai_whisper1_verbose_and_segments(monkeypatch, tmp_path):
    from asrkit import _http
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw)
        return _R(200, jsonobj={"text": "hi", "segments": [{"start": 0.0, "end": 1.0, "text": " hi"}]})

    monkeypatch.setattr(_http, "post", fake_post)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    a = registry.make_adapter("openai/whisper-1", {"api_key": "k"})
    r = a.transcribe(AudioInput(original_path=str(wav)), TranscribeOptions(lang_hint="en"))
    assert seen["data"]["response_format"] == "verbose_json"
    assert seen["data"]["timestamp_granularities[]"] == "segment"
    assert seen["data"]["language"] == "en"
    assert r.text == "hi" and r.segments and r.segments[0].start == 0.0 and r.segments[0].text == "hi"


def test_openai_no_segments_fallback(monkeypatch, tmp_path):
    from asrkit import _http
    monkeypatch.setattr(_http, "post", lambda url, **kw: _R(200, jsonobj={"text": "hi"}))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    a = registry.make_adapter("openai/whisper-1", {"api_key": "k"})
    r = a.transcribe(AudioInput(original_path=str(wav)), TranscribeOptions())
    assert r.text == "hi" and r.segments is None


def test_siliconflow_unchanged_p0_regression(monkeypatch, tmp_path):
    from asrkit import _http
    seen = {}
    monkeypatch.setattr(_http, "post", lambda url, **kw: (seen.update(kw), _R(200, jsonobj={"text": "hi"}))[1])
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    a = registry.make_adapter("siliconflow/sensevoice", {"api_key": "k"})
    r = a.transcribe(AudioInput(original_path=str(wav)), TranscribeOptions(lang_hint="zh"))
    # 三态 "none" 不被当真值:请求不含 verbose_json、不含 language;形状不变
    assert "response_format" not in seen["data"]
    assert "language" not in seen["data"]
    assert r.segments is None and r.text == "hi"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_segments.py -k openai -o addopts="" -v`;`-k siliconflow`
Expected: FAIL(现在不发 verbose_json、不解析 segments)

- [ ] **Step 3: 实现**

`cloud_openai.py`:import 加 `Segment`(`from ..types import AdapterMeta, AudioInput, BaseAdapter, Segment, TranscribeOptions, TranscribeResult`)。transcribe 里,把当前构造 form 与上传的段(W2 后已读 bytes)从:
```python
            resp = _http.post(
                f"{base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data={"model": self.meta.model},
                files={"file": (os.path.basename(audio.original_path), data)},
                timeout=120, idempotent=False)
```
改为(先建 form、门控):
```python
            from .. import capabilities
            caps = self.meta.capabilities or {}
            form = {"model": self.meta.model}
            if caps.get("segment_timestamps"):
                form["response_format"] = "verbose_json"
                form["timestamp_granularities[]"] = "segment"
            if capabilities.language_supported(self.meta) and opts.lang_hint:
                form["language"] = opts.lang_hint
            resp = _http.post(
                f"{base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data=form,
                files={"file": (os.path.basename(audio.original_path), data)},
                timeout=120, idempotent=False)
```
解析处把:
```python
            j = resp.json()
            return TranscribeResult(
                text=str(j.get("text") or j.get("result") or "").strip(),
                latency_ms=ms, raw_response=j)
```
改为:
```python
            j = resp.json()
            raw = j.get("segments")
            segs = ([Segment(s["start"], s["end"], s["text"].strip()) for s in raw]
                    if isinstance(raw, list) and raw else None)
            return TranscribeResult(
                text=str(j.get("text") or j.get("result") or "").strip(),
                segments=segs, latency_ms=ms, raw_response=j)
```
whisper-1 注册加 capabilities:`register_model(AdapterMeta(id="openai/whisper-1", ... model="whisper-1", config_schema={...}))` 里加 `capabilities={"language_hint": "supported", "segment_timestamps": True},`。**siliconflow 两条不动。**

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `PYTHONPATH=src python -m pytest tests/ -o addopts="" -q`
Expected: PASS(既有 82 + 新增;siliconflow 形状不变)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/adapters/cloud_openai.py tests/test_segments.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(openai): whisper-1 门控 verbose_json+timestamp_granularities+language 解析 segments;siliconflow 不变"
```

---

## Task 5: emit 批量把 warnings 打到 stderr

**Files:**
- Modify: `src/asrkit/emit.py`
- Test: `tests/test_batch.py`

**Interfaces:**
- Produces: 批量所有格式(json/csv/tsv/txt/mirror)每条记录若有 `result.warnings`,逐条打到 stderr。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_batch.py`)**

```python
def test_emit_prints_warnings_to_stderr(capsys):
    rec = {"file": "a.wav", "model": "m/x",
           "result": TranscribeResult(text="hi", warnings=["m/x auto-detects language; --language is ignored"]),
           "code": 0}
    emit.emit_batch(iter([rec]), fmt="csv", output=None)
    err = capsys.readouterr().err
    assert "[warn] a.wav:" in err and "ignored" in err
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -k warnings_to_stderr -o addopts="" -v`
Expected: FAIL(warnings 未打 stderr)

- [ ] **Step 3: 实现**

`emit.py` 顶部已 `import sys`。加一个小助手(放 `_ndjson_line` 附近):
```python
def _emit_warnings(rec) -> None:
    for w in (rec["result"].warnings or []):
        print(f'[warn] {rec["file"]}: {w}', file=sys.stderr)
```
在 `emit_batch` 的每个 stdout 分支(json / csv,tsv / txt)的 `for rec in records:` 循环体内,**处理该记录时**调用 `_emit_warnings(rec)`;在 `_mirror` 的 `for rec in records:` 循环体内同样调用。例如 json 分支:
```python
        for rec in records:
            _emit_warnings(rec)
            print(_ndjson_line(rec))
            if rec["result"].error:
                print(f'[error] {rec["file"]}: {rec["result"].error}', file=sys.stderr)
            codes.append(rec["code"])
```
(csv/tsv/txt/_mirror 循环体首行同样加 `_emit_warnings(rec)`。)

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/emit.py tests/test_batch.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(emit): 批量每条记录把 warnings 打到 stderr(全格式)"
```

---

## Task 6: 文档(result-contract + CHANGELOG)

**Files:**
- Modify: `docs/result-contract.md`、`CHANGELOG.md`

- [ ] **Step 1: 更新 `docs/result-contract.md`**

补:①`segments` 字段现由 whisper 家族填充(faster-whisper / whispercpp / openai/whisper-1);sherpa 与 transformers **暂不填**(TODO)。②能力位语义:`language_hint`(三态 `required/supported/none`)、`segment_timestamps`(模型返回 segments)。③选项诚实:对显式 `language_hint:"none"` 的模型传 `--language` 会得到 warning。

- [ ] **Step 2: 追加 `CHANGELOG.md` 的 `[Unreleased]`(不改版本号)**

在最新版本节之上新建 `## [Unreleased]`:
```markdown
## [Unreleased]

### 新增
- **字幕落地**:whisper 家族(faster-whisper / whispercpp / openai/whisper-1)现返回 `segments`,`srt/vtt` 对这些模型可用(此前对所有模型只报错)。
- **选项诚实**:对显式声明"忽略语言提示"的模型(如 SenseVoice)传 `--language` 会给出 warning,而非静默丢弃;新增 `capabilities.language_hint` 三态判读。
- whispercpp 现透传 `--language`(此前静默丢弃)。

### 说明
- openai/whisper-1 的 `verbose_json` 路径待真机验证;sherpa/transformers segments 与 word-level 时间戳为后续项。
```

- [ ] **Step 3: 提交**

```bash
git add docs/result-contract.md CHANGELOG.md
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "docs(w3a): 契约文档 segments/能力位 + CHANGELOG"
```

---

## Task 7: 收尾验证(ruff/mypy/全量)

**Files:** 无(纯验证)

- [ ] **Step 1: lint + 类型 + 全量**

Run:
```
ruff check src tests
mypy
PYTHONPATH=src python -m pytest tests/ -o addopts="" -q
```
Expected: ruff All checks passed;mypy Success;pytest 全绿(新增 test_capabilities/test_segments + 既有;e2e skip)。

- [ ] **Step 2: 有 lint/type 报错则 inline 修掉后重跑**

常见:`Segment` 未用/未导入、`capabilities` 循环 import。修到全绿。

- [ ] **Step 3: 提交(若 Step 2 有修改)**

```bash
git add -u
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "chore(w3a): lint/type 收尾"
```

---

## Self-Review 记录

- **Spec 覆盖**:三态 capabilities + 归一 + 告警 + api 接线 + sherpa 能力位(T1);faster-whisper 物化填 segments(T2);whispercpp 厘秒 + language(T3);openai 门控 verbose_json+granularities+language+解析 + siliconflow P0 回归(T4);emit 批量告警(T5);文档(T6);验证(T7)。✅
- **P0 三态**:全程经 `capabilities.language_supported/ignored`,`"none"` 绝不当真值;T4 `test_siliconflow_unchanged_p0_regression` 钉死。
- **类型一致**:`capabilities.language_supported/language_ignored/warnings_for`、`Segment(start,end,text)`、能力位键 `language_hint`(三态)/`segment_timestamps`(bool)跨任务一致。
- **不做**(YAGNI):sherpa/transformers segments、transformers language、元数据全量修真、`enable_punctuation`、word_timestamps 告警、serve 告警。
