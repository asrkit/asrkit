# W1 批量输入 + 结果契约化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `asrkit run/transcribe` 支持多文件/glob/目录/stdin 输入,并输出稳定契约(NDJSON + csv/tsv + 分级退出码),不动内核。

**Architecture:** 薄 CLI 聚合器。新增 `inputs.py`(解析输入→文件列表+清理回调)与 `emit.py`(批量发射+退出码);`formats.py` 加 `result_dict`;`cli.py` 编排。`api.transcribe()`/core/透明音频**不变**;批量复用**同一个 adapter 实例**(不每文件重载本地模型)。

**Tech Stack:** Python 3.9+,标准库 `glob`/`os`/`csv`/`json`/`tempfile`;pytest。无新运行时依赖。

## Global Constraints

- 版本号**不动**(`__version__` 保持 `0.5.1`);发版由人类定。落地默认下个 PATCH。
- base 运行时依赖仍只有 `requests`;**不加任何运行时依赖**。
- 终端输出/CLI 帮助/报错**一律英文**;代码注释中文。
- 透明音频:内核零处理,stdin 原样字节落临时文件,不解码。
- 单文件模式 stdout/stderr **输出字节与今天完全一致**(走原 `_print_result`);唯一可见变更是退出码分级。
- 提交用 `git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com"`,**显式 `git add <文件>`**,不 push。
- 退出码分级:`0` 成功 · `1` 意外异常 · `2` 用法错 · `3` 模型不存在 · `4` 转写/渲染失败。批量优先级 `1 > 3 > 4`。
- 契约细节见历史 spec：[`../specs/2026-07-07-w1-batch-input-and-result-contract-design.md`](../specs/2026-07-07-w1-batch-input-and-result-contract-design.md)。

---

## File Structure

- **Create** `src/asrkit/inputs.py` — `resolve(raw_args, *, stdin_format)` → `(paths, cleanups)`;`InputError`。glob/目录/白名单/stdin/fail-loud。
- **Create** `src/asrkit/emit.py` — 退出码常量 + `worst_code` + `emit_batch(records, *, fmt, output)`。NDJSON/csv/tsv/txt 聚合 + `-o` 目录镜像 + 流式。
- **Modify** `src/asrkit/formats.py` — 加 `result_dict(result)`(每结果 dict,`text` 恒含);`_json_payload` 改为复用它(单文件 json 输出不变)。
- **Modify** `src/asrkit/cli.py` — `run`/`transcribe` 位置参数 `nargs="+"`;加 `--batch`/`--stdin-format`;`-f` 加 `csv`/`tsv`;单/批分派 + 复用 adapter;`InputError`→2。
- **Modify** `src/asrkit/adapters/local_sherpa.py` — `metrics` 补 `duration_s`。
- **Create** `tests/test_inputs.py`、**Modify** `tests/test_formats.py`、**Create** `tests/test_batch.py`。
- **Create** `docs/result-contract.md`;**Modify** `docs/usage.md`、`CHANGELOG.md`。

---

## Task 1: 输入解析核心(文件/glob/目录,无 stdin)

**Files:**
- Create: `src/asrkit/inputs.py`
- Test: `tests/test_inputs.py`

**Interfaces:**
- Produces: `InputError(Exception)`;`resolve(raw_args: list[str], *, stdin_format: str = "wav") -> tuple[list[str], list]`(本任务先不处理 `-`)。`AUDIO_EXTS: set[str]`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_inputs.py
import pytest
from asrkit import inputs


def test_plain_files_passthrough_even_if_missing(tmp_path):
    a = tmp_path / "a.wav"; a.write_bytes(b"x")
    paths, cleanups = inputs.resolve([str(a), str(tmp_path / "missing.wav")])
    assert paths == sorted([str(a), str(tmp_path / "missing.wav")])
    assert cleanups == []


def test_glob_expands(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "b.wav").write_bytes(b"x")
    paths, _ = inputs.resolve([str(tmp_path / "*.wav")])
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["a.wav", "b.wav"]


def test_glob_no_match_fails_loud(tmp_path):
    with pytest.raises(inputs.InputError):
        inputs.resolve([str(tmp_path / "nope*.wav")])


def test_directory_recurses_with_whitelist(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "note.txt").write_bytes(b"x")
    sub = tmp_path / "sub"; sub.mkdir()
    (sub / "b.mp3").write_bytes(b"x")
    paths, _ = inputs.resolve([str(tmp_path)])
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["a.wav", "b.mp3"]


def test_directory_no_audio_fails_loud(tmp_path):
    (tmp_path / "note.txt").write_bytes(b"x")
    with pytest.raises(inputs.InputError):
        inputs.resolve([str(tmp_path)])


def test_empty_result_fails_loud():
    with pytest.raises(inputs.InputError):
        inputs.resolve([])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_inputs.py -v`
Expected: FAIL(`ModuleNotFoundError: asrkit.inputs` 或 AttributeError)

- [ ] **Step 3: 实现最小代码**

```python
# src/asrkit/inputs.py
"""输入解析：把 CLI 位置参数展开成有序、去重的音频文件列表。

支持:普通文件(即使不存在也入列,运行阶段自然报错)、glob(*?[)、目录递归(按扩展名白名单)、
stdin(-，见 stdin 处理)。glob/目录匹配 0 个 → fail loud(InputError)，绝不静默吞掉。
"""
from __future__ import annotations

import glob as _glob
import os
from typing import Callable, List, Tuple

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma", ".webm", ".amr"}
_GLOB_CHARS = ("*", "?", "[")


class InputError(Exception):
    """输入无法解析(空匹配 / 多个 stdin 等)。CLI 映射为退出码 2。"""


def _is_glob(s: str) -> bool:
    return any(c in s for c in _GLOB_CHARS)


def _collect_dir(d: str) -> List[str]:
    hits = []
    for root, _dirs, files in os.walk(d):
        for f in files:
            if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
                hits.append(os.path.join(root, f))
    return hits


def resolve(raw_args: List[str], *, stdin_format: str = "wav") -> Tuple[List[str], List[Callable]]:
    """返回 (有序去重文件路径, 清理回调)。本函数会为 stdin 产生副作用(见后续任务)。"""
    paths: List[str] = []
    cleanups: List[Callable] = []
    for arg in raw_args:
        if os.path.isdir(arg):
            hits = _collect_dir(arg)
            if not hits:
                raise InputError(f"directory '{arg}' has no audio files "
                                 f"({', '.join(sorted(AUDIO_EXTS))})")
            paths.extend(hits)
        elif _is_glob(arg) and not os.path.exists(arg):
            hits = _glob.glob(arg, recursive=True)
            if not hits:
                raise InputError(f"pattern '{arg}' matched no files")
            paths.extend(hits)
        else:
            paths.append(arg)          # 普通文件(即使不存在)
    out = sorted(dict.fromkeys(paths))  # 去重保序 + 排序确定性
    if not out:
        raise InputError("no audio inputs matched")
    return out, cleanups
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_inputs.py -v`
Expected: PASS(6 passed)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/inputs.py tests/test_inputs.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(inputs): 输入解析核心 — 文件/glob/目录递归 + fail-loud"
```

---

## Task 2: stdin 支持(`-`)

**Files:**
- Modify: `src/asrkit/inputs.py`
- Test: `tests/test_inputs.py`

**Interfaces:**
- Consumes: `resolve(raw_args, *, stdin_format="wav")`(Task 1)。
- Produces: `-` 读 stdin → 临时 `.{stdin_format}` 文件入列 + 清理回调;多个 `-` → `InputError`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_inputs.py 追加
import io
import os


def test_stdin_dash_writes_tempfile(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"RIFFDATA")))
    paths, cleanups = inputs.resolve(["-"], stdin_format="wav")
    assert len(paths) == 1 and paths[0].endswith(".wav")
    assert os.path.isfile(paths[0])
    with open(paths[0], "rb") as f:
        assert f.read() == b"RIFFDATA"
    for c in cleanups:
        c()
    assert not os.path.exists(paths[0])   # 清理回调删除临时文件


def test_stdin_format_override(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"x")))
    paths, cleanups = inputs.resolve(["-"], stdin_format="mp3")
    try:
        assert paths[0].endswith(".mp3")
    finally:
        for c in cleanups:
            c()


def test_multiple_stdin_rejected(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"x")))
    with pytest.raises(inputs.InputError):
        inputs.resolve(["-", "-"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_inputs.py -k stdin -v`
Expected: FAIL(`-` 被当普通文件,不产生临时文件)

- [ ] **Step 3: 实现最小代码**

在 `src/asrkit/inputs.py` 顶部加 import 与 stdin 处理。把 `resolve` 循环体开头加入 `-` 分支:

```python
import sys
import tempfile
```

在 `resolve` 函数内,循环前加计数;`for arg` 循环体**最前面**插入:

```python
    seen_stdin = False
    for arg in raw_args:
        if arg == "-":
            if seen_stdin:
                raise InputError("stdin '-' can appear at most once")
            seen_stdin = True
            data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") \
                else sys.stdin.read().encode()
            fd, tmp = tempfile.mkstemp(suffix="." + stdin_format.lstrip("."), prefix="asrkit_stdin_")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            paths.append(tmp)
            cleanups.append(lambda p=tmp: os.path.exists(p) and os.unlink(p))
            continue
        if os.path.isdir(arg):
            ...  # 保持原有分支
```

> 注:`sys.stdin.buffer` 在真实终端可用;测试用 `TextIOWrapper` 无 `.buffer`,故加 fallback 读文本再编码。`lambda p=tmp` 绑定当前值避免闭包晚绑定。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_inputs.py -v`
Expected: PASS(9 passed)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/inputs.py tests/test_inputs.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(inputs): stdin(-) 支持 — 单次/临时文件+清理回调/--stdin-format"
```

---

## Task 3: `formats.result_dict`(每结果 dict,text 恒含)

**Files:**
- Modify: `src/asrkit/formats.py`
- Test: `tests/test_formats.py`

**Interfaces:**
- Produces: `result_dict(result: TranscribeResult) -> dict`(`text` 恒含,即便 `""`;其它空字段略去;`segments` 转 dict)。`_json_payload` 复用它但对空 text 保持"略去"(单文件 json 输出不变)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_formats.py 追加
def test_result_dict_always_includes_text():
    from asrkit.types import TranscribeResult
    d = formats.result_dict(TranscribeResult(text="", error="boom"))
    assert d["text"] == ""          # 失败行也恒含 text
    assert d["error"] == "boom"


def test_result_dict_drops_other_empties_and_expands_segments():
    from asrkit.types import Segment, TranscribeResult
    d = formats.result_dict(TranscribeResult(text="hi", segments=[Segment(0.0, 1.0, "hi")]))
    assert d["text"] == "hi"
    assert "lang" not in d          # 空 lang 略去
    assert d["segments"][0]["text"] == "hi"


def test_single_json_still_drops_empty_text():
    from asrkit.types import TranscribeResult
    out = formats.render(TranscribeResult(text="", error="x"), "json")
    assert '"text"' not in out       # 单文件 json 行为不变
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_formats.py -k result_dict -v`
Expected: FAIL(`AttributeError: result_dict`)

- [ ] **Step 3: 实现最小代码**

在 `src/asrkit/formats.py` 中,把 `_json_payload` 重构为复用新 `result_dict`:

```python
def result_dict(r: TranscribeResult) -> dict:
    """每结果 → dict。`text` 恒含(即便空);其它空字段略去;segments 展开为 dict。
    批量 NDJSON/csv 取数用(失败行也要有 text)。"""
    out = {}
    for f in dataclasses.fields(r):
        v = getattr(r, f.name)
        if f.name == "text":
            out["text"] = v or ""
            continue
        if v in (None, "", [], {}):
            continue
        if f.name == "segments":
            v = [dataclasses.asdict(s) for s in v]
        out[f.name] = v
    return out


def _json_payload(r: TranscribeResult) -> str:
    # 单文件 json:复用 result_dict,但保持"空 text 略去"的历史行为(输出不变)。
    d = result_dict(r)
    if not d.get("text"):
        d.pop("text", None)
    return _json.dumps(d, ensure_ascii=False, indent=2)
```

删除原 `_json_payload` 旧实现(避免重复)。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_formats.py -v`
Expected: PASS(原有 + 3 新)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/formats.py tests/test_formats.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(formats): result_dict(text 恒含);_json_payload 复用(单文件 json 不变)"
```

---

## Task 4: `emit.py` — 退出码 + NDJSON 聚合

**Files:**
- Create: `src/asrkit/emit.py`
- Test: `tests/test_batch.py`

**Interfaces:**
- Consumes: `formats.result_dict`(Task 3)。
- Produces: 常量 `EXIT_OK/EXIT_ERROR/EXIT_USAGE/EXIT_MODEL_NOT_FOUND/EXIT_FAILED`;`SCHEMA_VERSION=1`;`worst_code(codes) -> int`;`code_for(result) -> int`;`emit_batch(records, *, fmt, output) -> int`。`records` 为可迭代的 dict:`{"file","model","result","code"}`。本任务只实现 stdout `json`(NDJSON)分支。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_batch.py
import json
from asrkit import emit
from asrkit.types import TranscribeResult


def _rec(file, text="", error=None, raw=None):
    r = TranscribeResult(text=text, error=error, raw_response=raw)
    return {"file": file, "model": "m/x", "result": r, "code": emit.code_for(r)}


def test_worst_code_priority():
    assert emit.worst_code([0, 4, 3, 1]) == 1     # 意外异常最优先
    assert emit.worst_code([0, 4, 3]) == 3
    assert emit.worst_code([0, 4]) == 4
    assert emit.worst_code([0, 0]) == 0


def test_ndjson_batch(capsys):
    recs = [_rec("a.wav", text="hello", raw={"x": 1}), _rec("b.wav", error="boom")]
    code = emit.emit_batch(iter(recs), fmt="json", output=None)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 2
    d0 = json.loads(lines[0])
    assert d0["file"] == "a.wav" and d0["model"] == "m/x"
    assert d0["schema_version"] == 1
    assert d0["text"] == "hello"
    assert "raw_response" not in d0          # 批量 NDJSON 排除 raw_response
    d1 = json.loads(lines[1])
    assert d1["text"] == "" and d1["error"] == "boom"
    assert code == emit.EXIT_FAILED
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -v`
Expected: FAIL(`ModuleNotFoundError: asrkit.emit`)

- [ ] **Step 3: 实现最小代码**

```python
# src/asrkit/emit.py
"""批量发射:把每条 Record 落地(stdout 聚合 / -o 目录镜像)并返回退出码。

流式:边消费边写,不囤全量结果。退出码优先级 1>3>4(意外异常绝不被转写失败掩盖)。
"""
from __future__ import annotations

import json as _json
import sys
from typing import Iterable

from . import formats

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_MODEL_NOT_FOUND = 3
EXIT_FAILED = 4
_PRIORITY = (EXIT_ERROR, EXIT_MODEL_NOT_FOUND, EXIT_FAILED)   # 1 > 3 > 4

SCHEMA_VERSION = 1


def code_for(result) -> int:
    return EXIT_FAILED if result.error else EXIT_OK


def worst_code(codes) -> int:
    nz = {c for c in codes if c}
    for c in _PRIORITY:
        if c in nz:
            return c
    return EXIT_OK


def _ndjson_line(rec) -> str:
    d = formats.result_dict(rec["result"])
    d.pop("raw_response", None)                 # 每行塞 vendor 原始响应是噪音
    d["file"] = rec["file"]
    d["model"] = rec["model"]
    d["schema_version"] = SCHEMA_VERSION
    return _json.dumps(d, ensure_ascii=False)


def emit_batch(records: Iterable[dict], *, fmt: str, output) -> int:
    if fmt == "json":
        codes = []
        for rec in records:
            print(_ndjson_line(rec))
            if rec["result"].error:
                print(f'[error] {rec["file"]}: {rec["result"].error}', file=sys.stderr)
            codes.append(rec["code"])
        return worst_code(codes)
    raise NotImplementedError(fmt)   # 其它格式在后续任务补
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/emit.py tests/test_batch.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(emit): 退出码(1>3>4)+ NDJSON 批量(schema_version、排除 raw_response)"
```

---

## Task 5: `emit.py` — csv/tsv + txt 聚合

**Files:**
- Modify: `src/asrkit/emit.py`
- Test: `tests/test_batch.py`

**Interfaces:**
- Consumes: `emit_batch`(Task 4)。
- Produces: `emit_batch` 支持 `fmt in ("csv","tsv","txt")`;列 `COLUMNS`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_batch.py 追加
import csv
import io


def test_csv_batch_columns_and_escaping(capsys):
    recs = [
        {"file": "a.wav", "model": "m/x",
         "result": TranscribeResult(text='he said "hi", bye\nnext', lang="en",
                                    latency_ms=12, metrics={"rtf": 0.5, "duration_s": 2.0}),
         "code": 0},
    ]
    code = emit.emit_batch(iter(recs), fmt="csv", output=None)
    out = capsys.readouterr().out
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == emit.COLUMNS
    assert rows[1][0] == "a.wav" and rows[1][2] == 'he said "hi", bye\nnext'  # 转义往返
    assert rows[1][emit.COLUMNS.index("rtf")] == "0.5"
    assert code == 0


def test_tsv_delimiter(capsys):
    recs = [{"file": "a.wav", "model": "m/x",
             "result": TranscribeResult(text="hi"), "code": 0}]
    emit.emit_batch(iter(recs), fmt="tsv", output=None)
    assert "\t" in capsys.readouterr().out.splitlines()[0]


def test_txt_batch_tab_separated(capsys):
    recs = [{"file": "a.wav", "model": "m/x",
             "result": TranscribeResult(text="hello"), "code": 0}]
    emit.emit_batch(iter(recs), fmt="txt", output=None)
    assert capsys.readouterr().out.splitlines()[0] == "a.wav\thello"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -k "csv or tsv or txt" -v`
Expected: FAIL(`NotImplementedError`)

- [ ] **Step 3: 实现最小代码**

在 `src/asrkit/emit.py` 顶部 import 加 `import csv`。加列定义与行取数,并扩展 `emit_batch`:

```python
COLUMNS = ["file", "model", "text", "lang", "duration_s", "latency_ms",
           "load_ms", "decode_ms", "rtf", "cost_estimate", "error"]


def _s(v) -> str:
    return "" if v is None else str(v)


def _row(rec) -> list:
    r = rec["result"]
    m = r.metrics or {}
    vals = {
        "file": rec["file"], "model": rec["model"],
        "text": r.text or "", "lang": r.lang or "",
        "duration_s": _s(m.get("duration_s")), "latency_ms": _s(r.latency_ms),
        "load_ms": _s(m.get("load_ms")), "decode_ms": _s(m.get("decode_ms")),
        "rtf": _s(m.get("rtf")), "cost_estimate": _s(r.cost_estimate),
        "error": r.error or "",
    }
    return [vals[c] for c in COLUMNS]
```

把 `emit_batch` 里 `if fmt == "json":` 之后、`raise NotImplementedError` 之前,加分支:

```python
    if fmt in ("csv", "tsv"):
        w = csv.writer(sys.stdout, delimiter="\t" if fmt == "tsv" else ",",
                       lineterminator="\n")     # 避免跨平台空行(Codex I)
        w.writerow(COLUMNS)
        codes = []
        for rec in records:
            w.writerow(_row(rec))
            codes.append(rec["code"])
        return worst_code(codes)
    if fmt == "txt":
        codes = []
        for rec in records:
            print(f'{rec["file"]}\t{rec["result"].text or ""}')
            if rec["result"].error:
                print(f'[error] {rec["file"]}: {rec["result"].error}', file=sys.stderr)
            codes.append(rec["code"])
        return worst_code(codes)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/emit.py tests/test_batch.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(emit): csv/tsv(newline 安全)+ txt 批量聚合"
```

---

## Task 6: `emit.py` — `-o <目录>` 镜像模式

**Files:**
- Modify: `src/asrkit/emit.py`
- Test: `tests/test_batch.py`

**Interfaces:**
- Consumes: `emit_batch`、`formats.render`。
- Produces: `emit_batch(..., output=<目录>)` → 每条 `formats.render` 写 `<目录>/<stem>.<fmt>`;stem 冲突 → `-1`/`-2`;`FormatError` 或 `result.error` → 该条 `EXIT_FAILED`,继续。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_batch.py 追加
def test_mirror_writes_per_file(tmp_path):
    recs = [
        {"file": "/x/a.wav", "model": "m", "result": TranscribeResult(text="AAA"), "code": 0},
        {"file": "/y/a.wav", "model": "m", "result": TranscribeResult(text="BBB"), "code": 0},
    ]
    code = emit.emit_batch(iter(recs), fmt="txt", output=str(tmp_path))
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["a.txt", "a-1.txt"] or names == ["a-1.txt", "a.txt"]  # 同名去重
    assert code == 0


def test_mirror_failed_record_counts_but_continues(tmp_path):
    recs = [
        {"file": "a.wav", "model": "m", "result": TranscribeResult(text="ok"), "code": 0},
        {"file": "b.wav", "model": "m", "result": TranscribeResult(text="", error="boom"), "code": 4},
    ]
    code = emit.emit_batch(iter(recs), fmt="txt", output=str(tmp_path))
    assert (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()       # 失败不写文件
    assert code == emit.EXIT_FAILED
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -k mirror -v`
Expected: FAIL(镜像分支未实现)

- [ ] **Step 3: 实现最小代码**

`src/asrkit/emit.py` 顶部 import 加 `import os`。在 `emit_batch` **函数体最前面**加镜像分派:

```python
def emit_batch(records: Iterable[dict], *, fmt: str, output) -> int:
    if output:
        return _mirror(records, fmt, output)
    # ...(下面保持原 stdout 分支:json / csv,tsv / txt)
```

在文件末尾加 `_mirror`:

```python
def _mirror(records: Iterable[dict], fmt: str, outdir: str) -> int:
    os.makedirs(outdir, exist_ok=True)
    used = set()
    codes = []
    for rec in records:
        r = rec["result"]
        if r.error:
            print(f'[error] {rec["file"]}: {r.error}', file=sys.stderr)
            codes.append(EXIT_FAILED)
            continue
        try:
            text = formats.render(r, fmt)
        except formats.FormatError as e:
            print(f'[error] {rec["file"]}: {e}', file=sys.stderr)
            codes.append(EXIT_FAILED)
            continue
        stem = os.path.splitext(os.path.basename(rec["file"]))[0]
        name = stem
        i = 1
        while name in used:
            name = f"{stem}-{i}"
            i += 1
        used.add(name)
        dest = os.path.join(outdir, f"{name}.{fmt}")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        codes.append(rec["code"])
    return worst_code(codes)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/emit.py tests/test_batch.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(emit): -o 目录镜像 — 逐文件写、同名去重、失败计数不中止"
```

---

## Task 7: sherpa `metrics` 补 `duration_s`

**Files:**
- Modify: `src/asrkit/adapters/local_sherpa.py`

**Interfaces:**
- Produces: sherpa 成功结果的 `metrics` 含 `duration_s`(csv `duration_s` 列本地不空)。

- [ ] **Step 1: 定位并改**

在 `src/asrkit/adapters/local_sherpa.py` 的 `transcribe` 里,`return TranscribeResult(... metrics={...})` 处,把 metrics 字典加一项 `"duration_s"`。当前是:

```python
                metrics={"load_ms": load_ms, "decode_ms": decode_ms,
                         "rtf": round((decode_ms / 1000) / dur, 4) if dur else None},
```

改为:

```python
                metrics={"load_ms": load_ms, "decode_ms": decode_ms,
                         "duration_s": round(dur, 3) if dur else None,
                         "rtf": round((decode_ms / 1000) / dur, 4) if dur else None},
```

- [ ] **Step 2: 静态验证不破坏冒烟**

Run: `PYTHONPATH=src python -m pytest tests/test_smoke.py -o addopts="" -q`
Expected: PASS(冒烟不依赖真引擎;此改只加字典键,真实覆盖走 nightly e2e)

- [ ] **Step 3: 提交**

```bash
git add src/asrkit/adapters/local_sherpa.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(sherpa): metrics 补 duration_s(csv 契约本地不空)"
```

---

## Task 8: `cli.py` 编排(nargs/flags/单批分派/复用 adapter)

**Files:**
- Modify: `src/asrkit/cli.py`
- Test: `tests/test_batch.py`

**Interfaces:**
- Consumes: `inputs.resolve`、`emit.emit_batch` + 退出码常量、`api._run_adapter`、`registry.make_adapter`/`ModelNotFoundError`。
- Produces: `run`/`transcribe` 接受多输入 + `--batch`/`--stdin-format` + `-f csv/tsv`;单文件模式输出不变;批量复用同一 adapter。

- [ ] **Step 1: 写失败测试(批量端到端 via stub)**

```python
# tests/test_batch.py 追加(端到端)
from asrkit import cli, registry
from asrkit.types import AdapterMeta, BaseAdapter


def _register_stub():
    @registry.register_protocol("stub-batch")
    class _Stub(BaseAdapter):
        def transcribe(self, audio, opts):
            import os
            name = os.path.basename(audio.original_path)
            if "bad" in name:
                return TranscribeResult(text="", error="stub failure")
            return TranscribeResult(text=f"T:{name}", lang="en", latency_ms=1)
    registry.register_model(AdapterMeta(
        id="stub/batch", provider="stub-batch", vendor="stub", name="Stub",
        source="cloud", modes=["batch"], langs=["en"]))


def test_cli_batch_ndjson_and_exit(tmp_path, capsys):
    _register_stub()
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "bad.wav").write_bytes(b"x")
    rc = cli.main(["transcribe", str(tmp_path), "-m", "stub/batch", "-f", "json"])
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 2
    assert rc == emit.EXIT_FAILED          # 有一个失败 → 非零


def test_cli_batch_flag_forces_aggregate(tmp_path, capsys):
    _register_stub()
    (tmp_path / "a.wav").write_bytes(b"x")
    rc = cli.main(["transcribe", str(tmp_path / "a.wav"), "-m", "stub/batch", "-f", "json", "--batch"])
    assert len(capsys.readouterr().out.splitlines()) == 1 and rc == 0


def test_cli_batch_srt_stdout_usage_error(tmp_path, capsys):
    _register_stub()
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "b.wav").write_bytes(b"x")
    rc = cli.main(["transcribe", str(tmp_path), "-m", "stub/batch", "-f", "srt"])
    assert rc == emit.EXIT_USAGE


def test_cli_single_unchanged(tmp_path, capsys):
    _register_stub()
    (tmp_path / "a.wav").write_bytes(b"x")
    rc = cli.main(["transcribe", str(tmp_path / "a.wav"), "-m", "stub/batch"])
    out = capsys.readouterr().out
    assert out.strip() == "T:a.wav" and rc == 0    # 单文件 txt 到 stdout,不带 file 前缀
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -k cli -v`
Expected: FAIL(位置参数还是单个 / 无 --batch / 无 csv 选项)

- [ ] **Step 3: 实现最小代码**

**(a)** `_add_transcribe_flags` 的 `-f` choices 扩展 + 加两个旗标:

```python
    sp.add_argument("-f", "--format", default="txt",
                    choices=("txt", "json", "srt", "vtt", "csv", "tsv"),
                    dest="format", help="output format (default: txt)")
    sp.add_argument("--batch", action="store_true",
                    help="force batch/aggregate output even for a single input "
                         "(stable NDJSON/csv for scripts)")
    sp.add_argument("--stdin-format", default="wav",
                    help="assumed format for stdin '-' input (default: wav)")
```

**(b)** `run`/`transcribe` 位置参数改 `nargs="+"`:

```python
    rp.add_argument("model")
    rp.add_argument("audio", nargs="+")
    _add_transcribe_flags(rp)

    tp.add_argument("audio", nargs="+")
    tp.add_argument("-m", "--model", required=True)
    tp.add_argument("--model-dir", default=None)
    _add_transcribe_flags(tp)
```

**(c)** 用一个共享分派函数替换 `run`/`transcribe` 两个 handler。把原 `if a.cmd == "run":` 与 `if a.cmd == "transcribe":` 两块替换为:

```python
    if a.cmd in ("run", "transcribe"):
        from . import emit, inputs
        try:
            files, cleanups = inputs.resolve(a.audio, stdin_format=a.stdin_format)
        except inputs.InputError as e:
            print(f"[error] {e}", file=sys.stderr)
            return emit.EXIT_USAGE
        try:
            raw = a.audio
            forced = a.batch
            multi = len(files) != 1 or any(
                arg == "-" or os.path.isdir(arg) or any(c in arg for c in "*?[")
                for arg in raw)
            batch = forced or multi
            cfg, opts = _cfg(a), _opts(a)

            # 单文件模式:输出与今天完全一致
            if not batch and a.format in ("txt", "json", "srt", "vtt"):
                fn = api.run if a.cmd == "run" else api.transcribe
                r = fn(a.model, files[0], config=cfg, opts=opts)
                return _batch_code(_print_result(r, fmt=a.format, output=a.output), r)

            # 批量/表格:字幕聚合到 stdout 不成立 → 用法错(fail fast)
            if not a.output and a.format in ("srt", "vtt"):
                print(f"[error] batch {a.format} needs -o <dir> "
                      f"(subtitles can't be aggregated to stdout)", file=sys.stderr)
                return emit.EXIT_USAGE

            # 复用同一 adapter(不每文件重载本地模型);模型不存在 → 3
            try:
                adapter = registry.make_adapter(a.model, cfg)
            except registry.ModelNotFoundError as e:
                print(f"[error] {e}", file=sys.stderr)
                return emit.EXIT_MODEL_NOT_FOUND
            if a.cmd == "run" and not adapter.is_installed():
                adapter.install()

            def _records():
                for f in files:
                    try:
                        res = api._run_adapter(adapter, a.model, f, opts)
                        code = emit.code_for(res)
                    except Exception as e:  # 意外异常 → 1,不掩盖
                        res = TranscribeResult(text="", error=f"{type(e).__name__}: {e}")
                        code = emit.EXIT_ERROR
                    yield {"file": f, "model": a.model, "result": res, "code": code}

            from .types import TranscribeResult
            return emit.emit_batch(_records(), fmt=a.format, output=a.output)
        finally:
            for c in cleanups:
                c()
```

**(d)** 加一个把 `_print_result` 的 `0/1` 提升为分级码的小助手(单文件模式用),放 `_print_result` 之后:

```python
def _batch_code(rc: int, r) -> int:
    """单文件:把 _print_result 的 0/1 细化为分级退出码(D9)。"""
    from . import emit
    if rc == 0:
        return emit.EXIT_OK
    return emit.EXIT_FAILED if r.error else emit.EXIT_ERROR
```

> 注:`import os` 已在 add-model 分支内局部 import;分派函数用到 `os`,在 `main` 顶部或本块开头 `import os`。在本块 `from . import emit, inputs` 同行加 `import os`。`TranscribeResult` 在生成器里用到,已在 (c) 末尾 import。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_batch.py -v`
Expected: PASS(全部)

- [ ] **Step 5: 全量回归 + 提交**

Run: `PYTHONPATH=src python -m pytest tests/ -o addopts="" -q`
Expected: PASS(既有 + 新增全绿;e2e skip)

```bash
git add src/asrkit/cli.py tests/test_batch.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(cli): 多输入/--batch/--stdin-format/csv-tsv;批量复用 adapter;退出码分级"
```

---

## Task 9: 文档 — 契约 + 用法 + CHANGELOG

**Files:**
- Create: `docs/result-contract.md`
- Modify: `docs/usage.md`、`CHANGELOG.md`

**Interfaces:** 无代码;文档化契约。

- [ ] **Step 1: 写 `docs/result-contract.md`**

内容涵盖:`TranscribeResult` 字段表(名/类型/含义/空值规则);单文件 `--format json`(空 text 略去、含 raw_response)vs 批量 NDJSON(`text` 恒含、加 `file`/`model`/`schema_version:1`、排除 raw_response)差异;csv/tsv 11 列定义(`file,model,text,lang,duration_s,latency_ms,load_ms,decode_ms,rtf,cost_estimate,error`)+ **"CSV 行数≠物理行数(text 含换行是合法多行记录),按 CSV 解析器读"**;退出码表 `0/1/2/3/4` + 批量优先级 `1>3>4`。

- [ ] **Step 2: 更新 `docs/usage.md`**

加批量小节:`asrkit transcribe *.wav -m X -f csv`、`asrkit transcribe ./dir -m X -f json --batch`、`cat a.wav | asrkit transcribe - -m X --stdin-format wav`、`-o <dir>` 镜像、退出码含义、"位置输入须连续"注意。

- [ ] **Step 3: 追加 `CHANGELOG.md` 一节(不改版本号)**

在最新版本节**之上**加(日期 2026-07-07,版本占位待人类定):

```markdown
## [Unreleased]

### 新增
- **批量 / 目录 / glob / stdin 输入**:`asrkit run/transcribe` 接受多个路径、目录(递归按扩展名收音频)、glob、`-`(stdin,`--stdin-format` 指定格式)。
- **`--batch`**:强制聚合输出(即便单文件),给脚本/评测稳定 NDJSON/csv。
- **结果契约化**:批量 `-f json` 出 **NDJSON**(每行加 `file`/`model`/`schema_version`);新增 **csv/tsv**(11 列);契约文档 `docs/result-contract.md`。
- 批量 `-o <dir>` 逐文件镜像;sherpa `metrics` 补 `duration_s`。

### 变更(行为)
- **退出码分级**(醒目):从"几乎都 1"改为 `0` 成功 / `1` 意外 / `2` 用法错 / `3` 模型不存在 / `4` 转写失败。批量取最严(优先级 `1>3>4`)。单文件转写失败退出码可能由 `1` 变 `4`。
```

- [ ] **Step 4: 提交**

```bash
git add docs/result-contract.md docs/usage.md CHANGELOG.md
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "docs(w1): 结果契约文档 + 用法 + CHANGELOG(退出码行为变更醒目)"
```

---

## Task 10: 收尾验证(ruff/mypy/全量)

**Files:** 无(纯验证)

- [ ] **Step 1: lint + 类型 + 全量测试**

Run(用隔离 venv 的 ruff/mypy,或 CI 会跑):
```
ruff check src tests
mypy
PYTHONPATH=src python -m pytest tests/ -o addopts="" -q
```
Expected: ruff All checks passed;mypy Success;pytest 全绿(新增 test_inputs/test_batch + 既有;e2e skip)。

- [ ] **Step 2: 若有 lint/type 报错,inline 修掉后重跑**

常见:`emit.py`/`inputs.py` 未用 import、类型标注。修到全绿。

- [ ] **Step 3: 提交(若 Step 2 有修改)**

```bash
git add -u
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "chore(w1): lint/type 收尾"
```

---

## Self-Review 记录

- **Spec 覆盖**:输入广度(T1/T2/T8)、NDJSON+schema_version(T4)、csv/tsv+11 列+转义(T5)、退出码 1>3>4(T4/T8)、`--batch`(T8)、stdin 生命周期(T2)、unmatched glob fail-loud(T1)、镜像+去重(T6)、duration_s(T7)、单文件不变(T8 回归)、契约文档+行为变更 CHANGELOG(T9)。✅ 全覆盖。
- **复用 adapter**:批量走 `api._run_adapter(adapter,...)` 共享实例,避免本地模型每文件重载(呼应 0.5.1 serve 修复)。
- **类型一致**:`emit.emit_batch(records, *, fmt, output)`、`emit.code_for/worst_code/COLUMNS/EXIT_*`、`formats.result_dict`、`inputs.resolve(...)->(paths,cleanups)`、`inputs.InputError` 全任务一致引用。
