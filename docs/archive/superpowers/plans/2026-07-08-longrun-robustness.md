# 长跑健壮性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修两颗长跑炸弹——doubao 轮询 30s 硬上限(长音频必失败)、serve adapter 缓存无界(内存泄漏)。

**Architecture:** doubao 改 wall-clock deadline 轮询 + 退避 + 可配超时;serve 改有界 `OrderedDict` LRU + 锁。两处独立文件,纯 bug 修复 + 向后兼容,新增两个 env 旋钮。

**Tech Stack:** Python 标准库(`math`/`threading`/`collections`);pytest + monkeypatch(mock `_http.post` / `registry.make_adapter`,不跑真网真模型)。

## Global Constraints

- **纯 bug 修复 + 向后兼容**:无契约/CLI/API 签名变更;无新运行时依赖(全标准库)。
- **i18n**:用户可见文案(error/help)**英文**;注释中文。
- **env 旋钮**:`ASRKIT_DOUBAO_POLL_TIMEOUT_S`(默认 300.0,非法/非有限/<=0 回退);`ASRKIT_SERVE_CACHE`(默认 8,非法/<=0 回退)。
- **doubao deadline 不溢出**:remaining-based,`remaining<=0` break,`sleep(min(interval, remaining))`,deadline 后不再排新 query。
- **serve 缓存**:`make_adapter` 在锁外;重入锁后**再查一次**缓存,命中返回已有;`while len>size: popitem(last=False)` 淘汰;异常不入缓存。
- **测试命令**:`PYTHONPATH=src python -m pytest <file> -o addopts="" -v`(必须 `PYTHONPATH=src`)。
- **提交**:`git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com"`,显式 `git add <具体文件>`,绝不 `git add .`。

---

### Task 1: doubao 轮询 deadline 化(`cloud_doubao.py`)

**Files:**
- Modify: `src/asrkit/adapters/cloud_doubao.py`(加 `import math`;加 `_poll_timeout_s()`;换轮询循环)
- Test: `tests/test_doubao_poll.py`(新建)

**Interfaces:**
- Consumes: 现有 `_http.post`、`time.sleep`/`time.perf_counter`、`TranscribeResult`、`os.environ`。
- Produces: `_poll_timeout_s() -> float`;deadline-based 轮询(行为:迟到成功不再受 30 次硬限;超时报实际值)。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_doubao_poll.py`(imports 置顶):

```python
"""Tests for doubao polling deadline/backoff (longrun robustness)."""
import pytest

from asrkit.adapters import cloud_doubao


def test_poll_timeout_env_fallbacks(monkeypatch):
    """非法/非有限/<=0 → 回退 300.0;合法正数 → 采用。"""
    for bad in ["inf", "nan", "abc", "0", "-5", ""]:
        monkeypatch.setenv("ASRKIT_DOUBAO_POLL_TIMEOUT_S", bad)
        assert cloud_doubao._poll_timeout_s() == 300.0
    monkeypatch.delenv("ASRKIT_DOUBAO_POLL_TIMEOUT_S", raising=False)
    assert cloud_doubao._poll_timeout_s() == 300.0
    monkeypatch.setenv("ASRKIT_DOUBAO_POLL_TIMEOUT_S", "120")
    assert cloud_doubao._poll_timeout_s() == 120.0


class _Resp:
    def __init__(self, status_code=200, headers=None, payload=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}
        self.text = text
    def json(self):
        return self._payload


def _make_adapter():
    from asrkit import registry
    return registry.make_adapter("doubao/auc-2", {"app_key": "k", "access_key": "s"})


def test_poll_late_success_not_truncated_at_30(monkeypatch):
    """第 40 次 query 才成功(>30)——不再被 30 次硬限截断。"""
    monkeypatch.setattr(cloud_doubao.time, "sleep", lambda *_: None)
    calls = {"n": 0}
    def fake_post(url, **kw):
        if url.endswith("/submit"):
            return _Resp(status_code=200)
        calls["n"] += 1
        if calls["n"] >= 40:
            return _Resp(headers={"x-api-status-code": "20000000"},
                         payload={"result": {"text": "done late"}})
        return _Resp(headers={"x-api-status-code": "20000001"})   # 处理中
    monkeypatch.setattr(cloud_doubao._http, "post", fake_post)
    from asrkit.types import AudioInput, TranscribeOptions
    ad = _make_adapter()
    # 用真文件路径避免 open 失败:指向本测试文件即可(仅读字节 base64)
    r = ad.transcribe(AudioInput(original_path=__file__), TranscribeOptions())
    assert r.error is None or r.error == ""
    assert r.text == "done late"
    assert calls["n"] >= 40


def test_poll_timeout_reports_actual_value(monkeypatch):
    """恒处理中 + 超时很小 → 报实际超时值,不无限轮询。"""
    monkeypatch.setattr(cloud_doubao.time, "sleep", lambda *_: None)
    monkeypatch.setattr(cloud_doubao, "_poll_timeout_s", lambda: 7.0)
    # perf_counter 递增桩:t0 一次,随后每轮跨过 deadline
    seq = iter([0.0, 1.0, 100.0, 200.0, 300.0])
    monkeypatch.setattr(cloud_doubao.time, "perf_counter", lambda: next(seq))
    def fake_post(url, **kw):
        if url.endswith("/submit"):
            return _Resp(status_code=200)
        return _Resp(headers={"x-api-status-code": "20000001"})
    monkeypatch.setattr(cloud_doubao._http, "post", fake_post)
    from asrkit.types import AudioInput, TranscribeOptions
    ad = _make_adapter()
    r = ad.transcribe(AudioInput(original_path=__file__), TranscribeOptions())
    assert r.error and "doubao polling timeout (7s)" in r.error
```

> 注:`transcribe` 会 `base64` 读取 `original_path`;用 `__file__` 作为存在的真实文件即可(内容无关,doubao 走 mock)。若 `_make_adapter` 的 model id/凭据参数与实际不符,实现者按 `models_local`/registry 真实 id 校正(doubao 的 model id 见 `cloud_doubao.py` 底部注册表,如 `doubao/auc-2`)。

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_doubao_poll.py -o addopts="" -v`
Expected: FAIL(`_poll_timeout_s` 不存在 / 旧 30 次循环行为不符)

- [ ] **Step 3: 实现**

在 `cloud_doubao.py` 顶部加 `import math`(与现有 import 同处,置顶,按字母序)。加模块级 helper:

```python
def _poll_timeout_s() -> float:
    """轮询总超时(秒)。env ASRKIT_DOUBAO_POLL_TIMEOUT_S 覆盖,非法/非有限/<=0 回退默认。"""
    raw = os.environ.get("ASRKIT_DOUBAO_POLL_TIMEOUT_S")
    if raw:
        try:
            v = float(raw)
            if math.isfinite(v) and v > 0:
                return v
        except ValueError:
            pass
    return 300.0
```

把 `cloud_doubao.py` 中现有轮询段:

```python
            for _ in range(30):
                time.sleep(1)
                q = _http.post(f"{base}/query", headers=headers, data="{}", timeout=60, idempotent=True)
                code = q.headers.get("x-api-status-code", "")
                if code == "20000000":
                    j = q.json()
                    text = (j.get("result") or {}).get("text") or j.get("text", "")
                    return TranscribeResult(
                        text=(text or "").strip(),
                        latency_ms=int((time.perf_counter() - t0) * 1000), raw_response=j)
                if code.startswith("45") or code.startswith("55"):
                    return TranscribeResult(text="", error=f"query failed code={code}: {q.text[:200]}")
            return TranscribeResult(text="", error="doubao polling timeout (30s)")
```

替换为:

```python
            poll_timeout = _poll_timeout_s()
            deadline = time.perf_counter() + poll_timeout
            interval = 1.0
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                time.sleep(min(interval, remaining))
                q = _http.post(f"{base}/query", headers=headers, data="{}", timeout=60, idempotent=True)
                code = q.headers.get("x-api-status-code", "")
                if code == "20000000":
                    j = q.json()
                    text = (j.get("result") or {}).get("text") or j.get("text", "")
                    return TranscribeResult(
                        text=(text or "").strip(),
                        latency_ms=int((time.perf_counter() - t0) * 1000), raw_response=j)
                if code.startswith("45") or code.startswith("55"):
                    return TranscribeResult(text="", error=f"query failed code={code}: {q.text[:200]}")
                interval = min(interval * 1.5, 5.0)
            return TranscribeResult(
                text="", error=f"doubao polling timeout ({int(poll_timeout)}s)")
```

- [ ] **Step 4: 运行确认通过 + lint**

Run: `PYTHONPATH=src python -m pytest tests/test_doubao_poll.py -o addopts="" -v` → PASS
Run: `PYTHONPATH=src python -m pytest -o addopts="" -q` → 全绿
Lint(隔离 venv,不存在退回 `python -m ruff`/`python -m mypy`,都无则跳过说明):
`/private/tmp/claude-501/-Users-user-asrkit/0de213e2-ade9-410d-a0a2-3948a4e35d2d/scratchpad/venv/bin/ruff check src/asrkit/adapters/cloud_doubao.py tests/test_doubao_poll.py`
`/private/tmp/claude-501/-Users-user-asrkit/0de213e2-ade9-410d-a0a2-3948a4e35d2d/scratchpad/venv/bin/mypy src/asrkit/adapters/cloud_doubao.py`

- [ ] **Step 5: 提交**

```bash
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" add src/asrkit/adapters/cloud_doubao.py tests/test_doubao_poll.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "fix(doubao): 轮询改 wall-clock deadline + 退避 + 可配超时(长音频不再 30s 截断)"
```

---

### Task 2: serve adapter 缓存有界化(`server.py`)

**Files:**
- Modify: `src/asrkit/server.py`(`_ADAPTERS` 改 `OrderedDict`;加 `threading`/`collections` import、`_cache_size()`、`_CACHE_LOCK`;重写 `_get_adapter`)
- Test: `tests/test_serve.py`(追加;勿动已有测试;import 置顶)

**Interfaces:**
- Consumes: 现有 `registry.make_adapter`、`registry.ModelNotFoundError`、`os.environ`。
- Produces: 有界 LRU `_get_adapter(model)`;`_cache_size() -> int`;`_ADAPTERS: OrderedDict`。

- [ ] **Step 1: 写失败测试(追加到 tests/test_serve.py)**

顶部 imports 补(置顶):
```python
from asrkit import server
```

追加:

```python
def _reset_cache():
    server._ADAPTERS.clear()


def test_serve_cache_hit_no_rebuild(monkeypatch):
    _reset_cache()
    calls = {"n": 0}
    def fake_make(model, *a, **k):
        calls["n"] += 1
        return object()
    monkeypatch.setattr(server.registry, "make_adapter", fake_make)
    a1 = server._get_adapter("m")
    a2 = server._get_adapter("m")
    assert a1 is a2 and calls["n"] == 1


def test_serve_cache_bounded_lru_evicts(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(server, "_cache_size", lambda: 2)
    monkeypatch.setattr(server.registry, "make_adapter", lambda model, *a, **k: object())
    server._get_adapter("A"); server._get_adapter("B"); server._get_adapter("C")
    assert len(server._ADAPTERS) == 2 and "A" not in server._ADAPTERS
    # A 被淘汰 → 再取会重建
    calls = {"n": 0}
    def counting(model, *a, **k):
        calls["n"] += 1
        return object()
    monkeypatch.setattr(server.registry, "make_adapter", counting)
    server._get_adapter("A")
    assert calls["n"] == 1


def test_serve_cache_hit_refreshes_lru(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(server, "_cache_size", lambda: 2)
    monkeypatch.setattr(server.registry, "make_adapter", lambda model, *a, **k: object())
    server._get_adapter("A"); server._get_adapter("B")
    server._get_adapter("A")            # 命中 A → A 最近
    server._get_adapter("C")            # 淘汰最久未用 = B
    assert "A" in server._ADAPTERS and "B" not in server._ADAPTERS


def test_serve_cache_exception_not_cached(monkeypatch):
    _reset_cache()
    def boom(model, *a, **k):
        raise server.registry.ModelNotFoundError("nope")
    monkeypatch.setattr(server.registry, "make_adapter", boom)
    with pytest.raises(server.registry.ModelNotFoundError):
        server._get_adapter("bad")
    assert "bad" not in server._ADAPTERS
```

顶部 imports 需有 `pytest`(若 test_serve.py 尚未 import,补上,置顶)。

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_serve.py -o addopts="" -v`
Expected: FAIL(`_cache_size` 不存在 / `_ADAPTERS` 非 OrderedDict 无淘汰)

- [ ] **Step 3: 实现**

`server.py` 顶部 import 区(现有 `import json as _json` / `import os` / `import sys` / `import tempfile`)补:
```python
import threading
from collections import OrderedDict
```

把:
```python
_ADAPTERS: dict = {}


def _get_adapter(model: str):
    a = _ADAPTERS.get(model)
    if a is None:
        a = registry.make_adapter(model)   # 可能抛 ModelNotFoundError
        _ADAPTERS[model] = a
    return a
```

替换为:
```python
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
```

> 保留原注释语义;`_ADAPTERS` 顶部旧注释一并更新为上面版本。

- [ ] **Step 4: 运行确认通过 + lint**

Run: `PYTHONPATH=src python -m pytest tests/test_serve.py -o addopts="" -v` → PASS
Run: `PYTHONPATH=src python -m pytest -o addopts="" -q` → 全绿
Lint:
`/private/tmp/claude-501/-Users-user-asrkit/0de213e2-ade9-410d-a0a2-3948a4e35d2d/scratchpad/venv/bin/ruff check src/asrkit/server.py tests/test_serve.py`
`/private/tmp/claude-501/-Users-user-asrkit/0de213e2-ade9-410d-a0a2-3948a4e35d2d/scratchpad/venv/bin/mypy src/asrkit/server.py`

- [ ] **Step 5: 提交**

```bash
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" add src/asrkit/server.py tests/test_serve.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "fix(serve): adapter 缓存改有界 LRU(默认 8,ASRKIT_SERVE_CACHE 可配),防长跑内存无界"
```

---

### Task 3: 文档 + CHANGELOG(controller 内联)

**Files:**
- Modify: `docs/usage.md`(记两个 env 旋钮)
- Modify: `CHANGELOG.md`(`[Unreleased]` 追加)

- [ ] **Step 1: usage.md**

在合适位置(云端重试段附近 / serve 段附近)记两个旋钮,英文键名 + 中文说明:
- `ASRKIT_DOUBAO_POLL_TIMEOUT_S`:doubao 录音文件识别轮询总超时秒数,默认 300;长音频需调大。
- `ASRKIT_SERVE_CACHE`:`asrkit serve` 的 adapter LRU 缓存容量,默认 8;多模型混合服务可调大。

- [ ] **Step 2: CHANGELOG `[Unreleased]` 追加**

```markdown
### 修复
- **doubao 长音频**:录音文件识别轮询从硬编码 30s 上限改为 wall-clock deadline + 退避,默认 300s(`ASRKIT_DOUBAO_POLL_TIMEOUT_S` 可配);长音频不再必然超时。
- **serve 内存**:`asrkit serve` 的 adapter 缓存从无界 dict 改为有界 LRU(默认 8,`ASRKIT_SERVE_CACHE` 可配),防长跑内存无界增长。
```

- [ ] **Step 3: 提交**

```bash
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" add docs/usage.md CHANGELOG.md
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "docs: doubao 轮询超时 + serve 缓存容量两个 env 旋钮 + CHANGELOG"
```

---

## Self-Review

- **Spec 覆盖**:D1/D2 → Task1(超时默认 300 + 退避);D3/D4 → Task2(LRU 默认 8 + OrderedDict/锁);Codex v2 三项:deadline 不溢出→Task1 remaining-based;缓存重查→Task2 重入锁再查;非有限浮点→Task1 `math.isfinite`。文档旋钮→Task3。
- **Placeholder**:无;每步给完整代码/测试。
- **类型一致**:`_poll_timeout_s()->float`、`_cache_size()->int`、`_get_adapter(model)` 签名不变;测试 monkeypatch 目标(`cloud_doubao.time`/`._http`/`_poll_timeout_s`、`server.registry.make_adapter`/`._cache_size`/`._ADAPTERS`)与实现一致。
- **顺序**:Task1、Task2 独立(不同文件)可任意序;Task3 文档最后。
