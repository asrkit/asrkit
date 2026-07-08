# 设计 — 麦克风流式输入(P3-C)

> 状态:brainstorming 完成、用户批准(Ctrl-C 停 + 打印最终文本),待 Codex 评审 → 实现计划。
> 定位约束:麦克风是 opt-in extra(`asrkit[mic]`),**内核仍零依赖**;复用 W4/E 的 `transcribe_stream`(麦克风只换 chunk 源);透明:直接采 16k 单声道 float32。

---

## 1. 背景

W4 让文件流式跑起来、E 让流式分段。C 补上**实时麦克风输入**:`asrkit stream <model> --mic`,边说边转,Ctrl-C 停并打印最终稿。麦克风 chunk 源接进已有 `SherpaLocal.transcribe_stream`,无需动引擎。

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 依赖 | 新 extra `asrkit[mic] = ["sounddevice", "numpy"]`;**不进 `all`**(sounddevice 需 PortAudio 系统库,保持专项);内核零依赖 |
| D2 | chunk 源 | `mic.record_chunks()` 持续采 16k 单声道 float32,喂 `transcribe_stream` |
| D3 | CLI | `asrkit stream <model> --mic`(`audio` 变可选 `nargs="?"`);`--device` 选设备 |
| D4 | 停止 UX | Ctrl-C 干净停;把已定稿 committed/最后文本打到 **stdout**(可管道);live → stderr |
| D5 | 不做 | VAD 预处理、设备枚举 UI、降噪、录制落文件 |

## 3. 设计

### 3.1 `pyproject.toml`

`transformers = [...]` 之后加:
```toml
mic = ["sounddevice", "numpy"]             # 麦克风实时输入:asrkit stream --mic
```
（`all` 不含 mic:sounddevice 依赖 PortAudio 系统库,保持独立 opt-in。）

### 3.2 `asrkit/mic.py`(新)

```python
"""麦克风流式输入源(opt-in extra: asrkit[mic])。
透明:直接采 16k 单声道 float32,喂 transcribe_stream;不做任何音频处理。"""
from __future__ import annotations

from typing import Any, Iterator, Optional

_INSTALL_HINT = 'mic input needs sounddevice. Run: pip install "asrkit[mic]"'


def record_chunks(samplerate: int = 16000, block_s: float = 0.1,
                  device: Optional[Any] = None) -> Iterator[Any]:
    """从麦克风持续采样,逐块 yield float32 单声道数组(约 samplerate*block_s 采样)。

    Ctrl-C(KeyboardInterrupt)→ 干净停止(return,让下游正常收尾)。
    缺 sounddevice → RuntimeError(友好提示)。
    """
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as e:
        raise RuntimeError(_INSTALL_HINT) from e
    blocksize = max(1, int(samplerate * block_s))
    stream = sd.InputStream(samplerate=samplerate, channels=1, dtype="float32",
                            blocksize=blocksize, device=device)
    stream.start()
    try:
        while True:
            data, _overflowed = stream.read(blocksize)          # (frames, 1) float32
            yield np.ascontiguousarray(data[:, 0], dtype=np.float32)
    except KeyboardInterrupt:
        return
    finally:
        stream.stop()
        stream.close()
```

### 3.3 `api.py`——抽共享校验 + 加 mic 入口

抽出 `_streaming_adapter`(供 file/mic 两个入口共用),`transcribe_stream` 改为用它(**保持 `window_s<=0` 检查在 make_adapter 之前**):

```python
def _streaming_adapter(model, config):
    adapter = registry.make_adapter(model, config or {})
    if "streaming" not in adapter.meta.modes:
        raise ValueError(f"{model} is not a streaming model")
    if not adapter.is_configured():
        raise ValueError(f"{model} is not configured (missing API key?)")
    return adapter


def transcribe_stream(model, audio, *, config=None, opts=None, window_s=0.1):
    """流式转写(文件分块)。仅 streaming 模型;及早校验。"""
    if window_s <= 0:
        raise ValueError("window_s must be > 0")
    adapter = _streaming_adapter(model, config)
    opts = opts or TranscribeOptions()
    from . import audio as _audio
    chunks = _audio.iter_file_chunks(audio, 16000, 1, window_s, convert=opts.convert)
    return adapter.transcribe_stream(chunks, opts)


def transcribe_stream_mic(model, *, config=None, opts=None,
                          samplerate=16000, block_s=0.1, device=None):
    """麦克风实时流式转写。仅 streaming 模型;返回 PartialResult 迭代器。
    需 asrkit[mic];Ctrl-C 停。"""
    adapter = _streaming_adapter(model, config)
    opts = opts or TranscribeOptions()
    from . import mic as _mic
    chunks = _mic.record_chunks(samplerate=samplerate, block_s=block_s, device=device)
    return adapter.transcribe_stream(chunks, opts)
```

### 3.4 CLI `stream`(`cli.py`)

解析器:`audio` 改 `nargs="?"`(可选),加 `--mic`、`--device`:
```python
    stp.add_argument("audio", nargs="?", default=None)
    stp.add_argument("--mic", action="store_true", help="read live audio from the microphone (needs asrkit[mic])")
    stp.add_argument("--device", default=None, help="microphone device index or name substring (with --mic)")
```

处理分支(替换现有 stream 分支;新增 mic 选择、缺依赖 RuntimeError、KeyboardInterrupt 收尾、last_text 兜底):
```python
    if a.cmd == "stream":
        from . import emit
        from .audio import AudioFormatError
        cfg, opts = _cfg(a), _opts(a)
        live = sys.stderr.isatty()
        try:
            if a.mic:
                dev = a.device
                if isinstance(dev, str) and dev.isdigit():
                    dev = int(dev)
                stream = api.transcribe_stream_mic(a.model, config=cfg, opts=opts, device=dev)
            else:
                if not a.audio:
                    print("[error] stream needs an audio file, or --mic", file=sys.stderr)
                    return emit.EXIT_USAGE
                stream = api.transcribe_stream(a.model, a.audio, config=cfg, opts=opts)
        except registry.ModelNotFoundError as e:
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_MODEL_NOT_FOUND
        except ValueError as e:
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_USAGE
        except RuntimeError as e:                 # mic 缺 sounddevice
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_ERROR
        last_text = ""
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
                    print(pr.text)
                    last_text = pr.text
                else:
                    last_text = pr.text
                    if live:
                        sys.stderr.write("\r\x1b[K" + pr.text); sys.stderr.flush()
        except AudioFormatError as e:
            if live:
                sys.stderr.write("\r\x1b[K"); sys.stderr.flush()
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_FAILED
        except KeyboardInterrupt:                 # mic Ctrl-C 兜底(若未在 record_chunks 内被吞)
            if live:
                sys.stderr.write("\r\x1b[K"); sys.stderr.flush()
            if last_text:
                print(last_text)
            return emit.EXIT_OK
        return emit.EXIT_OK
```

- 双保险:`record_chunks` 内吞 Ctrl-C → 下游正常 flush → is_final 打印;若 Ctrl-C 落在别处 → CLI `except KeyboardInterrupt` 打 `last_text`。两路都只打一次(互斥)。

## 4. 契约/行为影响

- 纯增量:新 `mic.py` + `api.transcribe_stream_mic` + `_streaming_adapter`(重构,行为等价)+ CLI `--mic`。文件流式路径**行为不变**(重构后 `transcribe_stream` 逻辑等价:window_s 检查仍在前)。
- 无内核新依赖;mic 依赖惰性 import。

## 5. 改动清单

| 文件 | 改动 |
|---|---|
| `pyproject.toml` | 加 `mic` extra |
| `src/asrkit/mic.py` | **新增** `record_chunks` |
| `src/asrkit/api.py` | 抽 `_streaming_adapter`;`transcribe_stream` 用它;加 `transcribe_stream_mic` |
| `src/asrkit/cli.py` | `stream` 加 `--mic`/`--device`、`audio` 可选、mic 分支 + Ctrl-C 收尾 |
| `tests/test_mic.py` | **新增** |
| `docs/usage.md` / `CHANGELOG.md` | 用法 + `[Unreleased]` |

## 6. 测试(mock sounddevice,不需硬件;numpy importorskip)

- **record_chunks 吐块 + Ctrl-C 停**:`sys.modules` 注入假 `sounddevice`(InputStream.read 前 N 次返回 `(np.zeros((bs,1),float32), False)`、第 N+1 次 `raise KeyboardInterrupt`);断言 record_chunks yield N 块后干净停(StopIteration),假 stream 的 stop/close 被调(finally)。
- **缺 sounddevice → RuntimeError**:`monkeypatch.setitem(sys.modules, "sounddevice", None)` 使 `import sounddevice` 抛 ImportError;断言 `next(record_chunks())` 抛 `RuntimeError` 且含 install hint。
- **api.transcribe_stream_mic 校验**:非流式 model(如 `openai/whisper-1`)→ `ValueError`(不碰麦克风)。
- **api.transcribe_stream 重构不回归**:现有 test_streaming 的 api 守卫测试仍绿(window_s<=0、非流式)。
- **CLI `--mic` 渲染**:`monkeypatch api.transcribe_stream_mic`→产假 partials(含 is_final);`capsys` 断言 stdout 有最终文本、EXIT_OK。
- **CLI `--mic` Ctrl-C 兜底**:假 stream 产一个非 final partial 后 `raise KeyboardInterrupt`;断言 stdout 打了 last_text、EXIT_OK。
- **CLI 无 audio 无 --mic → EXIT_USAGE**。
- **CLI mic 缺依赖**:`monkeypatch api.transcribe_stream_mic`→抛 `RuntimeError(hint)`;断言 EXIT_ERROR + stderr 提示。
- **回归**:现有 stream 文件测试仍绿。

## 7. 不做(YAGNI)

VAD、设备枚举命令、降噪、录制落文件、麦克风采样率自适配(固定 16k)。

## 8. 风险

- sounddevice 需系统 PortAudio;缺则友好报错,不进 `all` 避免连累 `pip install asrkit[all]`。
- 真机麦克风留手动验证;CI 全程 mock。
- KeyboardInterrupt 双路收尾:确保只打一次最终文本(record_chunks 吞则走 is_final,否则走 CLI 兜底)。
