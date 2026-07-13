# W4 最小流式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 ASRKit 加最小文件流式:`asrkit stream <model> <audio>` 对 sherpa online 模型逐块解码、边喂边出增量文本,真正行使 `PartialResult` 契约。

**Architecture:** 纯流处理器分层——`audio.iter_file_chunks` 把文件解码切成 16k 单声道窗口迭代器;`SherpaLocal.transcribe_stream`(非生成器外壳,call-time 校验能力)委托内层 `_stream` 生成器逐块喂在线识别器、逐块 yield `PartialResult`;`api.transcribe_stream` 及早校验(能力/window_s)后把两者串起来;CLI `stream` 子命令渲染(live→stderr、final→stdout)。零新运行时依赖。

**Tech Stack:** Python 3、sherpa-onnx OnlineRecognizer(可选引擎)、numpy(仅引擎路径)、pytest + monkeypatch(mock 引擎,不需真模型)。

## Global Constraints

- **零新运行时依赖**:只用文件分块 + 纯 Python;numpy 仅在 sherpa 引擎路径出现,测试用 `pytest.importorskip("numpy")`。
- **透明音频**:解码沿用 `load_samples` 的格式守卫;`convert=False` 且格式不符 → `AudioFormatError`(诚实报错),`--convert` opt-in。
- **契约只行使不改**:`PartialResult` 只写 `text` + `is_final`,`committed`/`partial` **留空**(契约允许);不改任何契约字段。
- **i18n**:终端输出/CLI 帮助/报错**一律英文**;注释与设计文档中文。
- **纯增量**:不动 batch 路径、不动云端、不动任何现有命令;现有 122 测试须仍绿。
- **退出码走 `emit.EXIT_*`**:正常 `EXIT_OK`(0);非流式/未配置/坏窗 `EXIT_USAGE`(2);模型未注册 `EXIT_MODEL_NOT_FOUND`(3);引擎未装/格式错/运行时失败 `EXIT_FAILED`(4)。
- **能力守卫语义**:`SherpaLocal.transcribe_stream` 外壳非生成器,非流式模型 **call-time** 抛 `NotImplementedError`;`api.transcribe_stream` 对不支持流式的 model **及早** 抛 `ValueError`(不进生成器)。
- **错误对称**:`_stream` 内 `_build`/缺文件/sherpa 运行时/解码异常收进末尾 `PartialResult(is_final=True, error=...)`;唯 `AudioFormatError` **re-raise**(交 CLI 格式错误分支)。
- **测试命令**:`PYTHONPATH=src python -m pytest tests/test_streaming.py -o addopts="" -v`(miniconda 有旧副本会遮蔽本地源码,必须 `PYTHONPATH=src`)。
- **提交**:`git -c user.name="BolynWang" -c user.email="1710998763@qq.com"`,显式 `git add <具体文件>`,绝不 `git add .`。

---

### Task 1: `audio.iter_file_chunks` — 文件分块 helper

**Files:**
- Modify: `src/asrkit/audio.py`(在 `load_samples` 之后追加)
- Test: `tests/test_streaming.py`(新建)

**Interfaces:**
- Consumes: `audio.load_samples(path, required_sr, required_channels, convert)`(现有)。
- Produces: `iter_file_chunks(path, sr=16000, channels=1, window_s=0.1, *, convert=False) -> Iterator[samples]` —— 逐个 yield float32 窗口(numpy 数组切片);解码失败 `AudioFormatError`(懒抛,首次 `next()`)。

- [ ] **Step 1: 写失败测试(分块正确 + 懒抛格式守卫)**

在新建 `tests/test_streaming.py` 顶部(imports 一律置顶,勿中途 import):

```python
"""Tests for W4 minimal streaming (iter_file_chunks / transcribe_stream / api / CLI)."""
import pytest

from asrkit import audio


def test_iter_file_chunks_slicing(monkeypatch):
    """iter_file_chunks 按窗切块,拼接还原,窗口数 = ceil(n/win)。"""
    seq = list(range(5000))
    monkeypatch.setattr(audio, "load_samples", lambda *a, **k: (seq, 16000))
    chunks = list(audio.iter_file_chunks("x.wav", 16000, 1, 0.1))
    assert [len(c) for c in chunks] == [1600, 1600, 1600, 200]     # win = 0.1*16000
    flat = [x for c in chunks for x in c]
    assert flat == seq


def test_iter_file_chunks_format_guard_lazy(monkeypatch):
    """格式不符 → AudioFormatError,在首次迭代时抛(生成器懒抛)。"""
    def boom(*a, **k):
        raise audio.AudioFormatError("bad format")
    monkeypatch.setattr(audio, "load_samples", boom)
    gen = audio.iter_file_chunks("x.wav")          # 构造不抛
    with pytest.raises(audio.AudioFormatError):
        next(iter(gen))                             # 首次迭代才抛
```

- [ ] **Step 2: 运行,确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_streaming.py -o addopts="" -v`
Expected: FAIL(`AttributeError: module 'asrkit.audio' has no attribute 'iter_file_chunks'`)

- [ ] **Step 3: 实现 `iter_file_chunks`**

在 `src/asrkit/audio.py` 末尾追加(注意 `from typing import ... Iterator` 已有 `Any, Tuple`,需补 `Iterator`):

先把文件顶部的 `from typing import Any, Tuple` 改为 `from typing import Any, Iterator, Tuple`,然后追加:

```python
def iter_file_chunks(
    path: str,
    sr: int = 16000,
    channels: int = 1,
    window_s: float = 0.1,
    *,
    convert: bool = False,
) -> Iterator[Any]:
    """解码文件为 sr/channels 后按固定窗切块,逐块 yield float32 采样。

    格式守卫沿用 load_samples:convert=False 且不符 → AudioFormatError(懒抛,首次迭代)。
    仅供流式 adapter 使用;window_s 由 api 层保证 > 0。
    """
    samples, actual_sr = load_samples(path, sr, channels, convert=convert)
    win = max(1, int(actual_sr * window_s))
    for i in range(0, len(samples), win):
        yield samples[i:i + win]
```

- [ ] **Step 4: 运行,确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_streaming.py -o addopts="" -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" add src/asrkit/audio.py tests/test_streaming.py
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "feat(audio): iter_file_chunks — 文件分块窗口迭代器(W4 流式地基)"
```

---

### Task 2: `SherpaLocal.transcribe_stream` — 引擎逐块解码

**Files:**
- Modify: `src/asrkit/adapters/local_sherpa.py`(加模块级 `_result_text`;`SherpaLocal` 加 `transcribe_stream` 外壳 + `_stream` 生成器)
- Test: `tests/test_streaming.py`(追加)

**Interfaces:**
- Consumes: 现有 `_available()`、`store.model_dir(meta, config)`、`_build(ct, d, threads, lang_hint, streaming, use_itn, prefer)`、`self._rec`、`self.meta`、`PartialResult`、`AudioFormatError`(已 import)。
- Produces:
  - `_result_text(r) -> str`:`r if isinstance(r, str) else getattr(r, "text", str(r))`。
  - `SherpaLocal.transcribe_stream(self, chunks, opts) -> Iterator[PartialResult]`:**非生成器外壳**,`"streaming" not in self.meta.modes` → call-time `raise NotImplementedError(...)`;否则 `return self._stream(chunks, opts)`。
  - `SherpaLocal._stream(self, chunks, opts)`:生成器,每块 yield `PartialResult(text=..., is_final=False)`,收尾 yield `is_final=True`;守卫/异常见 Global Constraints。

- [ ] **Step 1: 写失败测试(逐块产出 / call-time 守卫 / 错误对称 / AudioFormatError 穿透)**

在 `tests/test_streaming.py` 追加(顶部 imports 补 `from asrkit.adapters import local_sherpa`、`from asrkit.types import AdapterMeta, TranscribeOptions, PartialResult`):

```python
class _FakeStream:
    def __init__(self):
        self.fed = 0
    def accept_waveform(self, sr, samples):
        self.fed += 1
    def input_finished(self):
        pass


class _FakeRec:
    """get_result 随喂入块数递增,便于断言 text 增长。"""
    def create_stream(self):
        return _FakeStream()
    def is_ready(self, st):
        return False                       # 不进 decode 循环
    def decode_stream(self, st):
        pass
    def get_result(self, st):
        return "x" * st.fed


def _streaming_meta():
    return AdapterMeta(id="local/fake-stream", provider="sherpa-onnx", vendor="local",
                       name="Fake", source="local", modes=["streaming"], langs=["en"],
                       config_type="onlineParaformer")


def _batch_meta():
    return AdapterMeta(id="local/fake-batch", provider="sherpa-onnx", vendor="local",
                       name="Fake", source="local", modes=["batch"], langs=["en"],
                       config_type="senseVoice")


def _patch_engine(monkeypatch, tmp_path, rec):
    monkeypatch.setattr(local_sherpa, "_available", lambda: True)
    monkeypatch.setattr(local_sherpa.store, "model_dir", lambda meta, cfg: str(tmp_path))
    monkeypatch.setattr(local_sherpa, "_build", lambda *a, **k: rec)


def test_transcribe_stream_yields_growing_partials(monkeypatch, tmp_path):
    pytest.importorskip("numpy")
    ad = local_sherpa.SherpaLocal(_streaming_meta())
    _patch_engine(monkeypatch, tmp_path, _FakeRec())
    out = list(ad.transcribe_stream(iter([[0.0], [0.0], [0.0]]), TranscribeOptions()))
    assert len(out) == 4                                   # 3 块 + 1 定稿
    assert [p.is_final for p in out] == [False, False, False, True]
    texts = [p.text for p in out]
    assert texts == sorted(texts, key=len)                 # 递增
    assert all(p.committed == "" and p.partial == "" for p in out)   # 契约留空


def test_transcribe_stream_batch_model_raises_call_time(monkeypatch):
    """非流式模型:外壳非生成器,调用本身即抛(无需迭代)。"""
    ad = local_sherpa.SherpaLocal(_batch_meta())
    with pytest.raises(NotImplementedError):
        ad.transcribe_stream(iter([]), TranscribeOptions())    # 不 list(),调用即抛


def test_transcribe_stream_build_error_symmetric(monkeypatch, tmp_path):
    """_build 抛 → 收进末尾 PartialResult.error,不逃出生成器。"""
    pytest.importorskip("numpy")
    ad = local_sherpa.SherpaLocal(_streaming_meta())
    monkeypatch.setattr(local_sherpa, "_available", lambda: True)
    monkeypatch.setattr(local_sherpa.store, "model_dir", lambda meta, cfg: str(tmp_path))
    def boom(*a, **k):
        raise RuntimeError("no onnx files")
    monkeypatch.setattr(local_sherpa, "_build", boom)
    out = list(ad.transcribe_stream(iter([[0.0]]), TranscribeOptions()))
    assert out[-1].is_final is True
    assert out[-1].error and "streaming failed" in out[-1].error


def test_transcribe_stream_audioformat_error_propagates(monkeypatch, tmp_path):
    """AudioFormatError 从 chunks 迭代抛出 → 穿透 _stream,不被吞成 PartialResult.error。"""
    pytest.importorskip("numpy")
    ad = local_sherpa.SherpaLocal(_streaming_meta())
    _patch_engine(monkeypatch, tmp_path, _FakeRec())
    def bad_chunks():
        raise local_sherpa.AudioFormatError("bad wav")
        yield  # noqa (make it a generator)
    with pytest.raises(local_sherpa.AudioFormatError):
        list(ad.transcribe_stream(bad_chunks(), TranscribeOptions()))
```

- [ ] **Step 2: 运行,确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_streaming.py -o addopts="" -v`
Expected: FAIL(`AttributeError: 'SherpaLocal' object has no attribute 'transcribe_stream'` 走到基类的 `NotImplementedError` 但断言细节不符 / `_result_text` 未定义)

- [ ] **Step 3: 实现 `_result_text` + `transcribe_stream` + `_stream`**

在 `src/asrkit/adapters/local_sherpa.py` 顶部 import 处确认已有 `from ..types import ... PartialResult`(**没有则补** `PartialResult` 到那行 import),`AudioFormatError` 已在 `from ..audio import AudioFormatError, load_samples`。

在 `_decode_online` 附近(模块级)加:

```python
def _result_text(r) -> str:
    """归一 sherpa get_result 的返回(str 或带 .text 的对象)。"""
    return r if isinstance(r, str) else getattr(r, "text", str(r))
```

在 `SherpaLocal` 类内(`transcribe` 方法之后)加:

```python
    def transcribe_stream(self, chunks, opts):
        # 能力守卫:非流式模型不支持 —— 立即抛(外壳非生成器,保持基类 call-time 语义)
        if "streaming" not in self.meta.modes:
            raise NotImplementedError(
                f"{self.meta.id} is a batch model; streaming needs a streaming model")
        return self._stream(chunks, opts)

    def _stream(self, chunks, opts):
        if not _available():
            yield PartialResult(text="", is_final=True, error=_INSTALL_HINT)
            return
        import numpy as np
        d = store.model_dir(self.meta, self.config)
        if not os.path.isdir(d):
            yield PartialResult(
                text="", is_final=True,
                error=f"model not installed: {self.meta.id}. "
                      f"Run `asrkit pull {self.meta.id}` first.")
            return
        prefer = self.meta.tag or "int8"
        try:
            if self._rec is None:
                self._rec = _build(self.meta.config_type, d, 4,
                                   opts.lang_hint or "", True, opts.enable_itn, prefer)
            rec = self._rec
            st = rec.create_stream()
            sr = 16000                       # chunks 已是 16k 单声道 float32
            for chunk in chunks:
                st.accept_waveform(sr, chunk)
                while rec.is_ready(st):
                    rec.decode_stream(st)
                yield PartialResult(text=_result_text(rec.get_result(st)), is_final=False)
            st.accept_waveform(sr, np.zeros(sr // 2, dtype=np.float32))
            st.input_finished()
            while rec.is_ready(st):
                rec.decode_stream(st)
            yield PartialResult(text=_result_text(rec.get_result(st)), is_final=True)
        except AudioFormatError:
            raise                            # 交 CLI 格式错误分支(退 EXIT_FAILED),不吞
        except Exception as e:               # _build/缺文件/运行时/解码 → 对称收进 error
            yield PartialResult(text="", is_final=True, error=f"streaming failed: {e}")
```

- [ ] **Step 4: 运行,确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_streaming.py -o addopts="" -v`
Expected: PASS(6 passed;若无 numpy 则部分 skipped)

- [ ] **Step 5: 提交**

```bash
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" add src/asrkit/adapters/local_sherpa.py tests/test_streaming.py
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "feat(sherpa): transcribe_stream — 逐块喂在线识别器,行使 PartialResult 契约(W4)"
```

---

### Task 3: `api.transcribe_stream` — 公共流式入口

**Files:**
- Modify: `src/asrkit/api.py`
- Test: `tests/test_streaming.py`(追加)

**Interfaces:**
- Consumes: `registry.make_adapter(model, config)`(现有,不支持的 model 抛 `ModelNotFoundError`)、`adapter.meta.modes`、`adapter.is_configured()`、`adapter.transcribe_stream(chunks, opts)`(Task 2)、`audio.iter_file_chunks(path, sr, channels, window_s, convert)`(Task 1)、`TranscribeOptions`。
- Produces: `transcribe_stream(model, audio, *, config=None, opts=None, window_s=0.1) -> Iterator[PartialResult]`。及早校验:`window_s<=0` / 非流式 / 未配置 → `ValueError`(不进生成器)。

- [ ] **Step 1: 写失败测试(及早守卫)**

在 `tests/test_streaming.py` 追加(顶部 imports 补 `from asrkit import api, registry`):

```python
def test_api_stream_rejects_non_streaming_model():
    """非流式 model → 及早 ValueError(不迭代即抛)。"""
    with pytest.raises(ValueError):
        api.transcribe_stream("openai/whisper-1", "x.wav")    # 云端 batch 模型


def test_api_stream_rejects_bad_window():
    """window_s<=0 → 及早 ValueError。"""
    with pytest.raises(ValueError):
        api.transcribe_stream("local/fake-stream", "x.wav", window_s=0)
```

注:`local/fake-stream` 未注册会先抛 `ModelNotFoundError`(是 `ValueError` 子类吗?否)。为让 `window_s` 守卫先触发,**`window_s` 检查必须在 `make_adapter` 之前**。见 Step 3 顺序。

- [ ] **Step 2: 运行,确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_streaming.py -o addopts="" -v -k api_stream`
Expected: FAIL(`AttributeError: module 'asrkit.api' has no attribute 'transcribe_stream'`)

- [ ] **Step 3: 实现 `api.transcribe_stream`**

在 `src/asrkit/api.py` 末尾追加(`window_s` 校验置于 `make_adapter` 之前,使坏窗对任意 model 都及早抛;imports 顶部已有 `registry`、`TranscribeOptions`):

```python
def transcribe_stream(model, audio, *, config=None, opts=None, window_s=0.1):
    """流式转写:换 model 字符串即切模型。返回 PartialResult 迭代器。

    仅 modes 含 "streaming" 的模型可用。及早校验(不进生成器):
    window_s<=0 / 非流式模型 / 未配置 → ValueError;未注册模型 → ModelNotFoundError。
    """
    if window_s <= 0:
        raise ValueError("window_s must be > 0")
    adapter = registry.make_adapter(model, config or {})
    if "streaming" not in adapter.meta.modes:
        raise ValueError(f"{model} is not a streaming model")
    if not adapter.is_configured():
        raise ValueError(f"{model} is not configured (missing API key?)")
    opts = opts or TranscribeOptions()
    from . import audio as _audio
    chunks = _audio.iter_file_chunks(audio, 16000, 1, window_s, convert=opts.convert)
    return adapter.transcribe_stream(chunks, opts)
```

- [ ] **Step 4: 运行,确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_streaming.py -o addopts="" -v -k api_stream`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" add src/asrkit/api.py tests/test_streaming.py
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "feat(api): transcribe_stream — 薄公共流式入口,及早校验(W4)"
```

---

### Task 4: CLI `stream` 子命令

**Files:**
- Modify: `src/asrkit/cli.py`(加 `stream` 子解析器 + dispatch 分支)
- Test: `tests/test_streaming.py`(追加)

**Interfaces:**
- Consumes: `api.transcribe_stream`(Task 3)、`_cfg(a)`、`_opts(a)`、`emit.EXIT_*`、`registry.ModelNotFoundError`、`audio.AudioFormatError`、`sys.stderr.isatty()`。
- Produces: `asrkit stream <model> <audio>` 子命令;渲染 live→stderr(仅 tty)、final→stdout;退出码见 Global Constraints。

- [ ] **Step 1: 写失败测试(渲染 / 非流式 / 运行时失败)**

在 `tests/test_streaming.py` 追加(顶部 imports 补 `from asrkit import cli, emit`):

```python
def test_cli_stream_renders_final_to_stdout(monkeypatch, capsys):
    """最终文本进 stdout,退 EXIT_OK。"""
    def fake_stream(model, audio, *, config=None, opts=None):
        yield PartialResult(text="he", is_final=False)
        yield PartialResult(text="hello", is_final=True)
    monkeypatch.setattr(cli.api, "transcribe_stream", fake_stream)
    rc = cli.main(["stream", "local/fake-stream", "x.wav"])
    out = capsys.readouterr().out
    assert rc == emit.EXIT_OK
    assert "hello" in out


def test_cli_stream_non_streaming_usage(monkeypatch, capsys):
    """非流式 model(api 抛 ValueError)→ EXIT_USAGE,提示进 stderr。"""
    def boom(*a, **k):
        raise ValueError("openai/whisper-1 is not a streaming model")
    monkeypatch.setattr(cli.api, "transcribe_stream", boom)
    rc = cli.main(["stream", "openai/whisper-1", "x.wav"])
    err = capsys.readouterr().err
    assert rc == emit.EXIT_USAGE
    assert "not a streaming model" in err


def test_cli_stream_runtime_failure(monkeypatch, capsys):
    """PartialResult.error → EXIT_FAILED,[error] 进 stderr。"""
    def fake_stream(model, audio, *, config=None, opts=None):
        yield PartialResult(text="", is_final=True, error="streaming failed: boom")
    monkeypatch.setattr(cli.api, "transcribe_stream", fake_stream)
    rc = cli.main(["stream", "local/fake-stream", "x.wav"])
    err = capsys.readouterr().err
    assert rc == emit.EXIT_FAILED
    assert "[error]" in err
```

- [ ] **Step 2: 运行,确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_streaming.py -o addopts="" -v -k cli_stream`
Expected: FAIL(argparse 无 `stream` 子命令 → SystemExit 或 rc 非预期)

- [ ] **Step 3: 加子解析器**

在 `src/asrkit/cli.py` 的 `main()` 里,`transcribe` 解析器(`tp = sub.add_parser("transcribe", ...)` 块)之后、`a = p.parse_args(argv)` 之前追加:

```python
    stp = sub.add_parser("stream", help="stream-transcribe one file with a streaming model")
    stp.add_argument("model")
    stp.add_argument("audio")
    stp.add_argument("--model-dir", default=None)
    stp.add_argument("--language", default=None,
                     help="language hint (e.g. zh, en) — helps Whisper-family models")
    stp.add_argument("--convert", action="store_true",
                     help="decode/resample/downmix to fit the local engine "
                          "(off by default: on mismatch it errors)")
```

- [ ] **Step 4: 加 dispatch 分支**

在 dispatch 区(其它 `if a.cmd == "..."` 之间,建议紧邻 `transcribe`/`run` 分支)追加。`sys` 与 `os` 已在文件顶部/dispatch 处 import;`emit`、`registry`、`AudioFormatError` 局部 import:

```python
    if a.cmd == "stream":
        from . import emit
        from .audio import AudioFormatError
        cfg, opts = _cfg(a), _opts(a)      # 复用:lang_hint/convert(segment 对流式无意义,忽略)
        live = sys.stderr.isatty()
        try:
            stream = api.transcribe_stream(a.model, a.audio, config=cfg, opts=opts)
        except registry.ModelNotFoundError as e:
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_MODEL_NOT_FOUND
        except ValueError as e:            # 非流式模型 / 未配置 / window_s<=0
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_USAGE
        try:
            for pr in stream:
                if pr.error:
                    if live:
                        sys.stderr.write("\r\x1b[K"); sys.stderr.flush()
                    print(f"[error] {pr.error}", file=sys.stderr)
                    return emit.EXIT_FAILED
                if pr.is_final:
                    if live:
                        sys.stderr.write("\r\x1b[K"); sys.stderr.flush()
                    print(pr.text)                     # 最终 → stdout(可管道)
                elif live:
                    sys.stderr.write("\r\x1b[K" + pr.text); sys.stderr.flush()
        except AudioFormatError as e:        # 格式不符且未 --convert(穿透而来)
            if live:
                sys.stderr.write("\r\x1b[K"); sys.stderr.flush()
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_FAILED
        return emit.EXIT_OK
```

- [ ] **Step 5: 运行,确认通过 + 全量回归**

Run: `PYTHONPATH=src python -m pytest tests/test_streaming.py -o addopts="" -v`
Expected: PASS(全部)

Run: `PYTHONPATH=src python -m pytest -o addopts="" -q`
Expected: 现有 122 + 新增 全绿(numpy 缺失时相应 skipped)

- [ ] **Step 6: 提交**

```bash
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" add src/asrkit/cli.py tests/test_streaming.py
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "feat(cli): asrkit stream — 流式子命令,live→stderr/final→stdout(W4)"
```

---

### Task 5: 文档 + CHANGELOG + 契约行使复盘

**Files:**
- Modify: `docs/usage.md`(加 `asrkit stream` 用法)
- Modify: `docs/result-contract.md`(记 PartialResult 契约行使 + 复盘)
- Modify: `CHANGELOG.md`(`[Unreleased]` 追加)

**Interfaces:** 无代码;文档同步。

- [ ] **Step 1: `docs/usage.md` 加 stream 段**

在合适位置(transcribe 附近)加一节,英文示例 + 中文说明:

```markdown
## Streaming (minimal, local sherpa online models)

`asrkit stream <model> <audio>` incrementally decodes one file with a streaming
(online) sherpa model, printing a growing hypothesis live and the final text at the end.

```bash
asrkit stream local/paraformer-online x.wav       # live progress on stderr, final text on stdout
asrkit stream local/paraformer-online x.wav > out.txt   # only final text is captured
asrkit stream local/paraformer-online x.m4a --convert   # opt-in decode/resample
```

- Live partial results are written to **stderr** (overwriting one line, only when it is a TTY).
- The final transcript is written to **stdout** — safe to pipe/redirect.
- Only models whose `modes` include `streaming` are supported (`asrkit list --json` shows modes).
  A batch model errors with a clear message.
```

- [ ] **Step 2: `docs/result-contract.md` 记契约行使 + 复盘**

追加一节,记录 W4 真正行使了 `PartialResult`:

```markdown
## PartialResult 契约行使记录(W4)

`asrkit stream` 首次真正行使 `PartialResult`:
- **只用** `text`(权威展示文本)+ `is_final`。消费者一律以 `text` 为准。
- `committed`/`partial` **留空**(契约允许的可选优化);sherpa online 的增量假设直接给 `text`。
- `error` 承运行时失败(引擎未装 / streaming failed),随 `is_final=True` 一起给出。
- `ts_ms` 暂未填(文件分块无稳定挂钟语义;麦克风/serve 流式再议)。

**复盘(留给未来独立一刀)**:当前 `text=<完整假设>` 每块重发全量,消费者需自行 diff 才知新增;
若将来要"仅追加已定稿",再引入 `committed`/`partial` 精细化 —— 契约已预留字段,无需破坏性变更。
```

- [ ] **Step 3: `CHANGELOG.md` 的 `[Unreleased]` 追加**

在 `[Unreleased]` 段(与 W0–W3b3 累积项同列)加:

```markdown
- **流式(最小)**:新增 `asrkit stream <model> <audio>` 与 `api.transcribe_stream`,
  对 sherpa online 模型逐块解码、边喂边出增量文本(live→stderr、final→stdout);
  首次行使 `PartialResult` 契约(text+is_final)。零新依赖。
```

- [ ] **Step 4: 提交**

```bash
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" add docs/usage.md docs/result-contract.md CHANGELOG.md
git -c user.name="BolynWang" -c user.email="1710998763@qq.com" commit -m "docs(stream): usage + PartialResult 契约行使复盘 + CHANGELOG(W4)"
```

---

## Self-Review(计划作者已核)

- **Spec 覆盖**:D1(文件分块)→Task1;D2(契约只 text+is_final)→Task2 + Task5 复盘;D3(公共 API)→Task3;D4(stderr/stdout 分流)→Task4;D5(stream 子命令)→Task4;D6(仅 streaming 模型 + 守卫)→Task2(call-time)+Task3(及早);D7(YAGNI)→全程不碰。Codex v2 三项:非生成器外壳→Task2;错误对称→Task2;window_s 守卫→Task3。退出码对齐→Task4。
- **Placeholder 扫描**:无 TBD;每个代码步给出完整代码与测试。
- **类型一致**:`iter_file_chunks` 签名 Task1 定义、Task3 按 `(audio, 16000, 1, window_s, convert=...)` 调用一致;`transcribe_stream(chunks, opts)` Task2 定义、Task3 调用一致;`_result_text` Task2 内定义自用;`PartialResult(text, is_final, error, committed, partial)` 字段与 `types.py` 一致。
- **顺序依赖**:Task1(audio)→Task2(engine,不依赖 api/cli)→Task3(api,用 Task1+2)→Task4(cli,用 Task3)→Task5(docs)。每步可独立 review。
