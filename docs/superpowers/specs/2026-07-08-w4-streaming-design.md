# W4 设计 — 最小流式 `asrkit stream`(行使并校订 PartialResult 契约)

> 状态:brainstorming 完成、用户已批准三点取舍、**Codex(gpt-5.5)评审已采纳 3 项修订 → v2**,待写实现计划。
>
> **v2 修订**(Codex `.omc/artifacts/ask/codex-*2026-07-07T16-16-52*.md`):
> 1. `transcribe_stream` 拆成**非生成器外壳**(立即校验能力、call-time 抛 `NotImplementedError`)**+ 内层 `_stream` 生成器**——否则守卫延迟到首次 `next()` 才触发,直接调 adapter 的调用方拿不到基类式即时错误。
> 2. **错误对称**:`_build`/缺文件/sherpa 运行时/解码异常会逃出生成器,而 batch 收进 `TranscribeResult.error`。→ 包 try/except,末尾 yield `PartialResult(text="", is_final=True, error=...)`;但 **`AudioFormatError` re-raise**(交 CLI 格式错误分支,保持退 1)、**`ValueError`(不支持模型)仍及早抛**。
> 3. `window_s <= 0` 经 `max(1, int())` 静默退化成 1 样本/块(像卡死)→ `api.transcribe_stream` **及早 `ValueError`**。
> 波次:W4(求职方向最看重的一刀);落地默认下个 PATCH,**升号先问人类**。
> 定位约束:守"接口内核极薄";**零新运行时依赖**(文件分块、纯 Python);仅本地 sherpa online 模型;透明音频(格式不符诚实报错,`--convert` opt-in)。
>
> **本刀的元目的**:`PartialResult` 契约至今声明未用。真跑一遍流式,验证契约字段是否够用——这是 1.0 前的必经关(契约稳定性背书之一)。

---

## 1. 背景与目标

roadmap 把"最小流式"列为 W4。地基已在:`types.py` 有 `PartialResult` + `BaseAdapter.transcribe_stream`(声明即 `raise NotImplementedError`);`models_local.py` 注册了 13 个 `modes` 含 `"streaming"` 的 sherpa online 模型;`local_sherpa.py` 有 `_build(..., streaming=True, ...)` 建 `OnlineRecognizer` 和 `_decode_online`(一次性解码)。**缺的只是把它接成真流式**:逐块喂、逐块产出 `PartialResult`。

**目标**:`asrkit stream <model> <audio>` 对一个 streaming 模型逐块解码、边喂边出增量文本,最终定稿。**同时把 `PartialResult` 契约真正行使一次**。

---

## 2. 已定决策(用户批准)

| # | 决策 | 取值 |
|---|---|---|
| D1 | 输入源 | **文件分块**,零依赖;麦克风(需 sounddevice)/serve 流式(SSE/WS)**不做** |
| D2 | 契约行使范围 | 只填 `text`(权威)+ `is_final`;`committed`/`partial` **留空**(契约明写可选、端侧留空 OK);`ts_ms`/`error` 按需 |
| D3 | 公共 API | 加薄入口 `api.transcribe_stream(...)`(asrbench/程序可用) |
| D4 | 输出分流 | live partial → **stderr**(仅 tty 时 `\r` 覆盖同一行);最终文本 → **stdout**(可管道) |
| D5 | CLI 形态 | 新子命令 `asrkit stream <model> <audio>`(不污染批处理 `transcribe`) |
| D6 | 支持范围 | 仅 `modes` 含 `"streaming"` 的 sherpa online 模型;非流式模型 → 干净报错 |
| D7 | 不做 | 麦克风、serve 流式端点、非 sherpa 引擎流式、`committed`/`partial` 精细化、词级/说话人、VAD 端点检测 |

---

## 3. 设计

### 3.1 契约(不改字段,只行使)

`PartialResult` 字段维持现状(`text`/`committed`/`partial`/`is_final`/`ts_ms`/`error`)。本刀**只写 `text` + `is_final`**,其余留默认。行使后如发现契约不够用(例如缺"本段已终结"信号),在 spec 复盘记录——但**本刀不改契约**,避免边跑边动地基。

**语义**:每块解码后 yield 一个 `PartialResult(text=<当前完整假设>, is_final=False)`;喂完 flush 尾音后 yield 最终 `PartialResult(text=<最终文本>, is_final=True)`。消费者一律以 `text` 为准(权威展示文本)。

### 3.2 引擎侧 `SherpaLocal.transcribe_stream`(`adapters/local_sherpa.py`)

覆盖基类方法(基类默认 `raise NotImplementedError`)。因 `SherpaLocal` 同时承 batch+streaming 模型,**必须自守**:非 streaming 模型抛 `NotImplementedError`。**外壳非生成器**(能力校验 call-time 立即抛),内层 `_stream` 才是生成器(v2 修订 1)。

先加一个模块级小工具,归一 `get_result` 的返回(str 或带 `.text` 的对象):

```python
def _result_text(r) -> str:
    return r if isinstance(r, str) else getattr(r, "text", str(r))
```

```python
def transcribe_stream(self, chunks, opts):
    # 能力守卫:非流式模型不支持 —— 立即抛(非生成器,保持基类 call-time 语义)
    if "streaming" not in self.meta.modes:
        raise NotImplementedError(
            f"{self.meta.id} is a batch model; streaming needs a streaming model")
    return self._stream(chunks, opts)

def _stream(self, chunks, opts):
    # 引擎就绪守卫
    if not _available():
        yield PartialResult(text="", is_final=True, error=_INSTALL_HINT)
        return
    import numpy as np
    d = store.model_dir(self.meta, self.config)
    if not os.path.isdir(d):
        yield PartialResult(
            text="", is_final=True,
            error=f"model not installed: {self.meta.id}. Run `asrkit pull {self.meta.id}` first.")
        return
    prefer = self.meta.tag or "int8"
    try:
        # 建/复用在线识别器(与 batch 同一 _build,streaming=True)
        if self._rec is None:
            self._rec = _build(self.meta.config_type, d, 4,
                               opts.lang_hint or "", True, opts.enable_itn, prefer)
        rec = self._rec
        st = rec.create_stream()
        sr = 16000                       # chunks 已是 16k 单声道 float32
        # 逐块喂 + 逐块产出增量
        for chunk in chunks:
            st.accept_waveform(sr, chunk)
            while rec.is_ready(st):
                rec.decode_stream(st)
            yield PartialResult(text=_result_text(rec.get_result(st)), is_final=False)
        # flush 尾音 + 定稿(沿用 _decode_online 的 0.5s 静音收尾)
        st.accept_waveform(sr, np.zeros(sr // 2, dtype=np.float32))
        st.input_finished()
        while rec.is_ready(st):
            rec.decode_stream(st)
        yield PartialResult(text=_result_text(rec.get_result(st)), is_final=True)
    except AudioFormatError:
        raise                            # v2:交 CLI 格式错误分支(退 1),不吞
    except Exception as e:               # v2:_build/缺文件/运行时/解码 → 对称收进 error
        yield PartialResult(text="", is_final=True, error=f"streaming failed: {e}")
```

- **纯流处理器**:输入是"已解码的 16k 单声道 float32 窗口迭代器",不碰文件。这样麦克风将来只需换一个 chunk 源即可复用,无需动引擎。
- 复用 `self._rec` 缓存,与 `transcribe` 一致(`create_stream()` 每次新建,顺序复用无状态泄漏——Codex 确认)。
- `AudioFormatError`(来自 `chunks` 迭代内首个 `load_samples`)**re-raise**,不被通用 `except` 吞:CLI 仍走 `except AudioFormatError` 退 1。

### 3.3 文件分块 `audio.iter_file_chunks`(`audio.py`,新)

把"文件 → 窗口迭代器"独立成 helper(与 `load_samples` 同层,adapter 侧工具,**非 api 内核**):

```python
def iter_file_chunks(path, sr=16000, channels=1, window_s=0.1, *, convert=False):
    """解码文件为 16k 单声道后按固定窗切块。格式不符 → AudioFormatError(除非 convert)。"""
    samples, actual_sr = load_samples(path, sr, channels, convert=convert)
    win = max(1, int(actual_sr * window_s))
    for i in range(0, len(samples), win):
        yield samples[i:i + win]
```

- 透明音频:沿用 `load_samples` 的格式守卫,`convert=False` 且格式不符 → 抛 `AudioFormatError`(懒抛,在首次 `next()` 时)。
- `window_s=0.1`(1600 样本/块 @16k),块小则延迟低、产出勤。

### 3.4 公共 API `api.transcribe_stream`(`api.py`,新)

```python
def transcribe_stream(model, audio, *, config=None, opts=None, window_s=0.1):
    """流式转写:换 model 字符串即切模型。返回 PartialResult 迭代器。
    仅 streaming 模型可用;非流式模型抛 ValueError(及早,不进生成器)。"""
    if window_s <= 0:                                     # v2:防静默退化成 1 样本/块
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

- **及早**能力检查(非生成器包装):`model` 不支持流式 → 立刻 `ValueError`,不用等迭代。
- 解码只在此流式入口触发(opt-in),本地专用;云端 batch 路径(`transcribe`)不受影响、仍原样上传。

### 3.5 CLI `asrkit stream <model> <audio>`(`cli.py`)

```python
# 解析:sp.add_parser("stream", ...); 参数 model, audio, --convert, --language
if a.cmd == "stream":
    import sys
    from .audio import AudioFormatError
    opts = TranscribeOptions(convert=a.convert, lang_hint=a.language or "")
    live = sys.stderr.isatty()
    try:
        for p in api.transcribe_stream(a.model, a.audio, config=cfg, opts=opts):
            if p.error:
                print(p.error, file=sys.stderr)
                return 1
            if p.is_final:
                if live:
                    sys.stderr.write("\r\x1b[K")   # 清 live 行
                    sys.stderr.flush()
                print(p.text)                       # 最终 → stdout(可管道)
            elif live:
                sys.stderr.write("\r\x1b[K" + p.text)
                sys.stderr.flush()
    except ValueError as e:                          # 非流式模型 / 未配置
        print(str(e), file=sys.stderr)
        return 2
    except AudioFormatError as e:                     # 格式不符且未 --convert
        print(str(e), file=sys.stderr)
        return 1
    return 0
```

- **live 仅在 stderr 是 tty 时**做 `\r` 覆盖;管道/重定向时不吐 ANSI 噪音,只在 stdout 落最终文本。
- 退出码:非流式/未配置 = 2;格式错/模型未装 = 1;正常 = 0。

---

## 4. 契约/行为影响

- **纯增量**:新 `stream` 子命令 + `api.transcribe_stream` + `audio.iter_file_chunks` + `SherpaLocal.transcribe_stream`。不动 batch 路径、不动云端、不动任何现有命令。
- 新增公共 API `api.transcribe_stream` = **可寻址契约扩面**(但仍 0.x,PATCH;非破坏——纯新增)。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `src/asrkit/adapters/local_sherpa.py` | **新增** `_result_text` 工具 + `SherpaLocal.transcribe_stream`(非生成器外壳)+ `_stream`(内层生成器,逐块喂 online 识别器) |
| `src/asrkit/audio.py` | **新增** `iter_file_chunks(path, sr, channels, window_s, *, convert)` |
| `src/asrkit/api.py` | **新增** `transcribe_stream(model, audio, *, config, opts, window_s)` |
| `src/asrkit/cli.py` | **新增** `stream` 子命令 + 渲染 + 退出码 |
| `tests/test_streaming.py` | **新增** |
| `docs/usage.md` / `docs/result-contract.md` / `CHANGELOG.md` | 用法 + 契约行使记录 + `[Unreleased]` |

---

## 6. 测试(mock sherpa,不需真引擎;numpy 用 `importorskip`)

- **引擎逐块产出(`importorskip("numpy")`)**:构造 streaming meta 的 `SherpaLocal`;`monkeypatch` `_available`→True、`store.model_dir`→临时已存在目录、`_build`→返回 `FakeRec`(`create_stream`/`is_ready`(恒 False)/`decode_stream`(pass)/`get_result`→随喂入块数递增的文本)。喂 N 块 → 断言 yield N+1 个 `PartialResult`、`text` 递增、最后一个 `is_final=True` 且前 N 个 `is_final=False`、**所有项 `committed==""` 且 `partial==""`**。
- **非流式模型守卫(v2:call-time)**:batch-only meta 的 `SherpaLocal`,`pytest.raises(NotImplementedError)` 包 **`adapter.transcribe_stream(iter([]), opts)` 这次调用本身**(外壳非生成器,不需 `list()` 即抛;须先于 `_available` 检查触发)。
- **建/解码异常对称收进 error(v2,`importorskip("numpy")`)**:`_build` monkeypatch 成抛 `RuntimeError`(或 `FakeRec.decode_stream` 抛),迭代 → 最后一个 `PartialResult` 的 `is_final=True` 且 `error` 含 "streaming failed";异常**不逃出**生成器。
- **`AudioFormatError` 不被吞(v2)**:`chunks` 迭代首个即抛 `AudioFormatError`(用会抛的假 chunks 迭代器),断言它**穿透** `_stream` 传播出来(`pytest.raises(AudioFormatError)`),不变成 `PartialResult.error`。
- **`window_s<=0` 及早守卫(v2)**:`api.transcribe_stream(streaming_model, path, window_s=0)` → `pytest.raises(ValueError)`(不迭代即抛)。
- **`iter_file_chunks` 分块正确(无需 numpy)**:`monkeypatch audio.load_samples`→返回(长度 5000 的序列, 16000);断言产出 4 块(1600/1600/1600/200)、拼接等于原序列、窗口数 = ceil(5000/1600)。
- **`iter_file_chunks` 格式守卫**:`monkeypatch load_samples`→抛 `AudioFormatError`;断言迭代首个即抛。
- **`api.transcribe_stream` 及早守卫**:非流式 model → `pytest.raises(ValueError)`(不迭代即抛)。
- **CLI `stream` 渲染**:`monkeypatch api.transcribe_stream`→产假 partials(`text="he"`, 然后 `text="hello", is_final=True`);`capsys` 断言 **stdout 含最终 "hello"**、返回 0。
- **CLI `stream` 非流式**:`monkeypatch api.transcribe_stream`→抛 `ValueError`;断言 stderr 有提示、返回 2。
- **回归**:不影响 `transcribe`/其它命令(现有 122 测试仍绿)。

---

## 7. 明确不做(YAGNI)

麦克风输入、serve 的 SSE/WebSocket 流式、非 sherpa 引擎流式、`committed`/`partial` 精细化、词级时间戳、说话人、VAD 端点检测、流式 `--format` 多格式输出。

---

## 8. 风险与兼容

- **纯新增**:回归面限于新代码;batch/云端/现有命令零改动。
- **契约不改**:只行使不动字段,避免边跑边改地基;行使发现的不足记入 spec 复盘,留给未来独立一刀。
- **numpy 依赖**:仅引擎级测试需要,`importorskip` 兜底;分块/CLI/api 守卫测试不依赖 numpy。
- **live 渲染**:仅 tty 覆盖行,管道安全(stdout 只落最终文本)。
