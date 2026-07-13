# W2 云端重试 + 下载源可自定义 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给云端 adapter 加共享 Session + 分级重试(计费 POST 只重 429/连接失败,只读重全部),并加 `asrkit pull --url` 一次性下载覆盖。

**Architecture:** 新增 `asrkit/_http.py`(线程局部 Session + 手写重试),5 个云端 adapter + doubao submit/poll 改走它;`pull --url` 经 `install(url=)` 边界透传到 `store.pull`。零新运行时依赖。

**Tech Stack:** Python 3.9+;`requests`(base 唯一依赖,自带);stdlib `threading`/`email.utils`/`uuid`/`random`;pytest + unittest.mock。

## Global Constraints

- 版本号**不动**(`__version__` 仍 `0.5.1`);发版由人类定。
- **零新增运行时依赖**;base 仍只 `requests`。
- 终端/CLI 帮助/报错**英文**;代码注释**中文**。
- **成本安全**:计费 POST(转写、doubao submit)只重 `429` + `ConnectTimeout`;**不重** 5xx / 读超时 / 泛连接错。只读(doubao query 轮询)重 `429`+`{500,502,503,504}`+所有连接/超时。
- 云端 adapter **请求形状逐字不变**,只把 `requests.post` 换成 `_http.post`;成功路径零改变;**全程 mock,不打真实 API**。
- 提交用 `git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com"`,**显式 `git add <文件>`**,不 push。
- **测试一律** `PYTHONPATH=src python -m pytest ... -o addopts=""`(仓库有 miniconda 旧副本会遮蔽本地源码)。
- 契约细节见历史 spec：[`../specs/2026-07-07-w2-cloud-retry-and-download-override-design.md`](../specs/2026-07-07-w2-cloud-retry-and-download-override-design.md)。

---

## File Structure

- **Create** `src/asrkit/_http.py` — 线程局部 Session + `post(idempotent=...)` 重试 + `_backoff`/`_retry_after`/`_sleep`/`_retries`。
- **Modify** `src/asrkit/adapters/cloud_doubao.py` — uuid request-id 复用;submit `idempotent=False` / query `idempotent=True`。
- **Modify** `cloud_openai.py`、`cloud_elevenlabs.py`(读 bytes + 200MB 守卫 + basename)、`cloud_dashscope.py`(路由)。
- **Modify** `src/asrkit/types.py`(`BaseAdapter.install` 加 `url`)、`local_sherpa.py`(透传)、`local_faster_whisper.py`/`local_whispercpp.py`/`local_transformers.py`(加 `url=None` 忽略)、`store.py`(`effective_url` + http(s) 限制)、`api.py`、`cli.py`。
- **Create** `tests/test_http.py`;**Create** `tests/test_cloud_retry.py`;**Modify** `tests/test_smoke.py`(pull --url)。
- **Modify** `docs/usage.md`、`CHANGELOG.md`。

---

## Task 1: `_http.py` — 共享 Session + 分级重试

**Files:**
- Create: `src/asrkit/_http.py`
- Test: `tests/test_http.py`

**Interfaces:**
- Produces: `post(url, *, idempotent=False, retries=None, **kwargs) -> requests.Response`;`_session()`、`_retries()`、`_backoff(attempt)`、`_retry_after(resp)`、`_sleep(seconds)`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_http.py
import datetime
import email.utils

import pytest
from unittest.mock import Mock
from requests.exceptions import ConnectTimeout, ReadTimeout
from requests.exceptions import ConnectionError as ReqConnErr

from asrkit import _http


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


@pytest.fixture
def fake(monkeypatch):
    sess = Mock()
    slept = []
    monkeypatch.setattr(_http, "_session", lambda: sess)
    monkeypatch.setattr(_http, "_sleep", lambda s: slept.append(s))
    monkeypatch.delenv("ASRKIT_HTTP_RETRIES", raising=False)
    return sess, slept


def test_billable_retries_429_then_200(fake):
    sess, _ = fake
    sess.post.side_effect = [_Resp(429), _Resp(429), _Resp(200)]
    assert _http.post("http://x", idempotent=False).status_code == 200
    assert sess.post.call_count == 3


def test_billable_does_not_retry_500(fake):
    sess, _ = fake
    sess.post.side_effect = [_Resp(500), _Resp(200)]
    assert _http.post("http://x", idempotent=False).status_code == 500
    assert sess.post.call_count == 1


def test_idempotent_retries_500(fake):
    sess, _ = fake
    sess.post.side_effect = [_Resp(500), _Resp(200)]
    assert _http.post("http://x", idempotent=True).status_code == 200
    assert sess.post.call_count == 2


def test_connect_timeout_retried_even_billable(fake):
    sess, _ = fake
    sess.post.side_effect = [ConnectTimeout(), _Resp(200)]
    assert _http.post("http://x", idempotent=False).status_code == 200
    assert sess.post.call_count == 2


def test_read_timeout_not_retried_billable(fake):
    sess, _ = fake
    sess.post.side_effect = [ReadTimeout()]
    with pytest.raises(ReadTimeout):
        _http.post("http://x", idempotent=False)
    assert sess.post.call_count == 1


def test_read_timeout_retried_idempotent(fake):
    sess, _ = fake
    sess.post.side_effect = [ReadTimeout(), _Resp(200)]
    assert _http.post("http://x", idempotent=True).status_code == 200
    assert sess.post.call_count == 2


def test_generic_connection_error_not_retried_billable(fake):
    sess, _ = fake
    sess.post.side_effect = [ReqConnErr()]
    with pytest.raises(ReqConnErr):
        _http.post("http://x", idempotent=False)
    assert sess.post.call_count == 1


def test_retry_after_seconds(fake):
    sess, slept = fake
    sess.post.side_effect = [_Resp(429, {"Retry-After": "3"}), _Resp(200)]
    _http.post("http://x", idempotent=False)
    assert slept and slept[0] == 3.0


def test_retry_after_http_date(fake):
    sess, slept = fake
    future = email.utils.format_datetime(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5))
    sess.post.side_effect = [_Resp(429, {"Retry-After": future}), _Resp(200)]
    _http.post("http://x", idempotent=False)
    assert slept and 0 < slept[0] <= 30


def test_retries_exhausted_returns_last(fake, monkeypatch):
    sess, _ = fake
    monkeypatch.setenv("ASRKIT_HTTP_RETRIES", "2")
    sess.post.side_effect = [_Resp(429), _Resp(429), _Resp(429)]
    assert _http.post("http://x", idempotent=False).status_code == 429
    assert sess.post.call_count == 3


def test_retries_env_parsing(monkeypatch):
    monkeypatch.setenv("ASRKIT_HTTP_RETRIES", "abc")
    assert _http._retries() == 3
    monkeypatch.setenv("ASRKIT_HTTP_RETRIES", "-1")
    assert _http._retries() == 0
    monkeypatch.setenv("ASRKIT_HTTP_RETRIES", "0")
    assert _http._retries() == 0


def test_backoff_capped():
    for attempt in range(6):
        assert _http._backoff(attempt) <= 8.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_http.py -o addopts="" -v`
Expected: FAIL(`ModuleNotFoundError: asrkit._http`)

- [ ] **Step 3: 实现**

```python
# src/asrkit/_http.py
"""共享 HTTP:线程局部 Session + 手写重试/退避。

云端 adapter 都走 _http.post(不再各自一次性 requests.post)。按调用区分策略:
- idempotent=False(默认,计费/create POST:转写、doubao submit):只重 429 + ConnectTimeout
  (服务端拒绝或从未到达 → 零双扣费);不重 5xx / 读超时 / 泛连接错。
- idempotent=True(只读:doubao 轮询 query):重 429+{500,502,503,504}+所有连接/超时。
零新依赖(requests 自带)。
"""
from __future__ import annotations

import datetime as _dt
import email.utils
import os
import random
import threading
import time
from typing import Optional

import requests
from requests.exceptions import ConnectionError as _ConnectionError
from requests.exceptions import ConnectTimeout, ReadTimeout, Timeout

_local = threading.local()
_BACKOFF_BASE = 0.5
_BACKOFF_CAP = 8.0
_RETRY_AFTER_CAP = 30.0
_DEFAULT_RETRIES = 3
_IDEMPOTENT_STATUS = {429, 500, 502, 503, 504}
_BILLABLE_STATUS = {429}


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()          # 线程局部:serve 线程池下各线程独立,无 cookie/header 竞争
        _local.session = s
    return s


def _retries() -> int:
    raw = os.environ.get("ASRKIT_HTTP_RETRIES")
    if raw is None:
        return _DEFAULT_RETRIES
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_RETRIES
    return max(0, min(n, 10))


def _backoff(attempt: int) -> float:
    d = min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_CAP)
    d *= 1 + random.uniform(0, 0.25)
    return min(d, _BACKOFF_CAP)          # 抖动后再 clamp


def _retry_after(resp: requests.Response) -> Optional[float]:
    v = (resp.headers.get("Retry-After") or "").strip()
    if not v:
        return None
    if v.isdigit():                      # delta-seconds
        return min(float(v), _RETRY_AFTER_CAP)
    try:                                 # HTTP-date
        when = email.utils.parsedate_to_datetime(v)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    now = _dt.datetime.now(when.tzinfo) if when.tzinfo else _dt.datetime.now()
    return max(0.0, min((when - now).total_seconds(), _RETRY_AFTER_CAP))


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def post(url: str, *, idempotent: bool = False, retries: Optional[int] = None, **kwargs) -> requests.Response:
    n = retries if retries is not None else _retries()
    codes = _IDEMPOTENT_STATUS if idempotent else _BILLABLE_STATUS
    for attempt in range(n + 1):
        try:
            resp = _session().post(url, **kwargs)
        except ConnectTimeout:           # 从未到达服务端 → 计费/只读都安全重
            if attempt == n:
                raise
            _sleep(_backoff(attempt))
            continue
        except (ReadTimeout, _ConnectionError, Timeout):  # 可能已发出/已处理 → 仅只读重
            if idempotent and attempt < n:
                _sleep(_backoff(attempt))
                continue
            raise
        if resp.status_code in codes and attempt < n:
            _sleep(_retry_after(resp) or _backoff(attempt))
            continue
        return resp
    raise AssertionError("unreachable")  # 循环必在 return/raise 收尾
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_http.py -o addopts="" -v`
Expected: PASS(全部)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/_http.py tests/test_http.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(http): 线程局部 Session + 分级重试(计费只重 429/ConnectTimeout,只读重全部)"
```

---

## Task 2: doubao — uuid 幂等键 + 分策略路由

**Files:**
- Modify: `src/asrkit/adapters/cloud_doubao.py`
- Test: `tests/test_cloud_retry.py`

**Interfaces:**
- Consumes: `_http.post`(Task 1)。
- Produces: doubao submit 走 `idempotent=False`、query 走 `idempotent=True`,二者共用一个 `uuid4` 的 `X-Api-Request-Id`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cloud_retry.py
import uuid

from asrkit import _http, registry
from asrkit.types import AudioInput, TranscribeOptions


class _R:
    def __init__(self, status=200, headers=None, jsonobj=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self._j = jsonobj or {}
        self.text = text

    def json(self):
        return self._j


def test_doubao_uuid_and_policies(tmp_path, monkeypatch):
    from asrkit.adapters import cloud_doubao
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw.get("idempotent"), kw["headers"]["X-Api-Request-Id"]))
        if url.endswith("/submit"):
            return _R(200)
        return _R(200, headers={"x-api-status-code": "20000000"},
                  jsonobj={"result": {"text": "hi"}})

    monkeypatch.setattr(_http, "post", fake_post)
    monkeypatch.setattr(cloud_doubao.time, "sleep", lambda s: None)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    a = registry.make_adapter("doubao/auc-2", {"api_key": "k"})
    r = a.transcribe(AudioInput(original_path=str(wav)), TranscribeOptions())
    assert r.text == "hi"
    submit = next(c for c in calls if c[0].endswith("/submit"))
    query = next(c for c in calls if c[0].endswith("/query"))
    assert submit[1] is False and query[1] is True     # 分策略
    assert submit[2] == query[2]                        # 同一 request-id
    uuid.UUID(submit[2])                                # 是合法 uuid
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_cloud_retry.py::test_doubao_uuid_and_policies -o addopts="" -v`
Expected: FAIL(现用 `requests.post` 且 request-id 是时间戳)

- [ ] **Step 3: 实现**

在 `src/asrkit/adapters/cloud_doubao.py`:
- 顶部 import 加 `import uuid` 和 `from .. import _http`。
- `transcribe` 内删掉 `import requests`。
- request-id 改用 uuid:把
  ```python
      "X-Api-Request-Id": str(int(time.time() * 1e6)),
  ```
  改为(在构造 headers 前先 `req_id = str(uuid.uuid4())`):
  ```python
      "X-Api-Request-Id": req_id,
  ```
- submit 与 query 改走 `_http.post`,带 `idempotent`:
  ```python
      sub = _http.post(f"{base}/submit", headers=headers, json={
          "user": {"uid": "asrkit"},
          "audio": {"format": "wav", "data": b64},
          "request": {"model_name": self.meta.model},
      }, timeout=60, idempotent=False)
  ```
  ```python
          q = _http.post(f"{base}/query", headers=headers, data="{}", timeout=60, idempotent=True)
  ```
  其余(状态码判断、轮询循环、结果解析)不变。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_cloud_retry.py -o addopts="" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/adapters/cloud_doubao.py tests/test_cloud_retry.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(doubao): uuid 幂等 request-id 复用;submit 计费/query 只读走 _http"
```

---

## Task 3: openai / elevenlabs / dashscope 路由 `_http`(+ 上传守卫)

**Files:**
- Modify: `src/asrkit/adapters/cloud_openai.py`、`cloud_elevenlabs.py`、`cloud_dashscope.py`
- Test: `tests/test_cloud_retry.py`

**Interfaces:**
- Consumes: `_http.post`。
- Produces: 三家转写走 `idempotent=False`;openai/elevenlabs 上传体为 `(basename, bytes)` 且 >200MB 友好报错。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_cloud_retry.py`)**

```python
def test_openai_uploads_bytes_and_idempotent_false(tmp_path, monkeypatch):
    from asrkit.adapters import cloud_openai
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw)
        return _R(200, jsonobj={"text": "hello"})

    monkeypatch.setattr(_http, "post", fake_post)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFFDATA")
    a = registry.make_adapter("openai/whisper-1", {"api_key": "k"})
    r = a.transcribe(AudioInput(original_path=str(wav)), TranscribeOptions())
    assert r.text == "hello"
    assert seen.get("idempotent") is False
    name, data = seen["files"]["file"]
    assert name == "a.wav" and data == b"RIFFDATA"     # basename + bytes(可重发)


def test_openai_size_guard(tmp_path, monkeypatch):
    from asrkit.adapters import cloud_openai
    wav = tmp_path / "big.wav"
    wav.write_bytes(b"x")
    monkeypatch.setattr(cloud_openai.os, "path", cloud_openai.os.path)
    monkeypatch.setattr(cloud_openai.os.path, "getsize", lambda p: 201 * 1024 * 1024)
    a = registry.make_adapter("openai/whisper-1", {"api_key": "k"})
    r = a.transcribe(AudioInput(original_path=str(wav)), TranscribeOptions())
    assert r.text == "" and "200MB" in (r.error or "")


def test_dashscope_routes_through_http(tmp_path, monkeypatch):
    from asrkit.adapters import cloud_dashscope
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw)
        return _R(200, jsonobj={"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(_http, "post", fake_post)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    a = registry.make_adapter("dashscope/qwen3-asr-flash", {"api_key": "k"})
    r = a.transcribe(AudioInput(original_path=str(wav)), TranscribeOptions())
    assert r.text == "hi"
    assert seen.get("idempotent") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_cloud_retry.py -k "openai or dashscope" -o addopts="" -v`
Expected: FAIL(仍用 requests.post / 无 size 守卫 / files 是句柄)

- [ ] **Step 3: 实现**

**cloud_openai.py**:顶部加 `import os` 和 `from .. import _http`;`transcribe` 里删 `import requests`,把上传段改为:
```python
            base = self.config.get("base_url") or self.meta.default_base_url
            sz = os.path.getsize(audio.original_path)
            if sz > 200 * 1024 * 1024:
                return TranscribeResult(
                    text="", error=f"audio is {sz >> 20}MB, over the 200MB upload "
                    "limit; segment the file first")
            t0 = time.perf_counter()
            with open(audio.original_path, "rb") as f:
                data = f.read()
            resp = _http.post(
                f"{base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data={"model": self.meta.model},
                files={"file": (os.path.basename(audio.original_path), data)},
                timeout=120, idempotent=False)
```
(其余解析不变。)

**cloud_elevenlabs.py**:顶部加 `import os` 和 `from .. import _http`;`transcribe` 里删 `import requests`,改为:
```python
            base = self.config.get("base_url") or self.meta.default_base_url
            sz = os.path.getsize(audio.original_path)
            if sz > 200 * 1024 * 1024:
                return TranscribeResult(
                    text="", error=f"audio is {sz >> 20}MB, over the 200MB upload "
                    "limit; segment the file first")
            t0 = time.perf_counter()
            with open(audio.original_path, "rb") as f:
                data = f.read()
            r = _http.post(base, headers={"xi-api-key": key},
                           data={"model_id": self.meta.model},
                           files={"file": (os.path.basename(audio.original_path), data)},
                           timeout=120, idempotent=False)
```

**cloud_dashscope.py**:顶部加 `from .. import _http`;`_post` 里删 `import requests`,把 `r = requests.post(...)` 改为 `r = _http.post(url, headers={...}, json=body, timeout=120, idempotent=False)`(headers/body 不变)。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python -m pytest tests/test_cloud_retry.py -o addopts="" -v`
Expected: PASS(全部)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/adapters/cloud_openai.py src/asrkit/adapters/cloud_elevenlabs.py src/asrkit/adapters/cloud_dashscope.py tests/test_cloud_retry.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(cloud): openai/elevenlabs/dashscope 转写走 _http(idempotent=False);两家补 200MB 守卫+读 bytes"
```

---

## Task 4: `pull --url` 一次性下载覆盖

**Files:**
- Modify: `src/asrkit/types.py`、`src/asrkit/adapters/local_sherpa.py`、`local_faster_whisper.py`、`local_whispercpp.py`、`local_transformers.py`、`src/asrkit/store.py`、`src/asrkit/api.py`、`src/asrkit/cli.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: `store.pull(meta, config=None, log=print, *, url=None)`(url 优先于 meta.download_url,限 http(s));`BaseAdapter.install(self, log=print, url=None)`;`api.pull(model, *, config=None, url=None, log=print)`;CLI `pull --url`。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_smoke.py`)**

```python
def test_pull_url_override(tmp_path, monkeypatch):
    import io
    import os
    import shutil
    import tarfile

    from asrkit import store
    from asrkit.types import AdapterMeta
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(tmp_path / "models"))
    tar = tmp_path / "src.tar.bz2"
    with tarfile.open(tar, "w:bz2") as tf:
        info = tarfile.TarInfo("model.onnx")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    monkeypatch.setattr(store, "_download",
                        lambda url, path, log, timeout=30: shutil.copy(str(tar), path))
    meta = AdapterMeta(id="local/urltest", provider="sherpa-onnx", vendor="local",
                       name="x", source="local", modes=["batch"], langs=[], download_url="")
    d = store.pull(meta, {}, url="http://example.com/whatever.tar.bz2")
    assert os.path.exists(os.path.join(d, "model.onnx"))   # 用了覆盖 URL


def test_pull_url_rejects_non_http(tmp_path, monkeypatch):
    from asrkit import store
    from asrkit.types import AdapterMeta
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(tmp_path / "models"))
    meta = AdapterMeta(id="local/x2", provider="sherpa-onnx", vendor="local",
                       name="x", source="local", modes=["batch"], langs=[], download_url="")
    with pytest.raises(ValueError):
        store.pull(meta, {}, url="file:///etc/passwd")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python -m pytest tests/test_smoke.py -k pull_url -o addopts="" -v`
Expected: FAIL(`pull()` 无 `url` 关键字参数)

- [ ] **Step 3: 实现**

**types.py** — `BaseAdapter.install` 加 `url`:
```python
    def install(self, log=print, url=None) -> str:
        """本地引擎覆盖:下载/安装模型或引擎,返回位置。url 可覆盖默认下载地址(仅 sherpa 用)。"""
        raise ValueError(f"{self.meta.id} needs no install")
```

**store.py** — `pull` 加 `url` 并用 `effective_url`。把签名与开头改为:
```python
def pull(meta: AdapterMeta, config: dict | None = None, log=print, *, url: str | None = None) -> str:
    """下载并安装本地模型(原子)。已装则直接返回模型目录。url 覆盖 meta.download_url(限 http/https)。"""
    if meta.source != "local":
        raise ValueError(f"{meta.id} is not a local model; no pull needed")
    dest = model_dir(meta, config)
    if is_installed(meta, config):
        log(f"already installed: {dest}")
        return dest
    effective_url = url or meta.download_url
    if not effective_url:
        raise ValueError(f"{meta.id} has no download URL")
    if not effective_url.startswith(("http://", "https://")):
        raise ValueError(f"refusing non-http(s) download URL: {effective_url}")
```
并把后面 `log(f"downloading {meta.download_url}")` / `_download(meta.download_url, ...)` 两处的 `meta.download_url` 改为 `effective_url`。

**local_sherpa.py** — 透传:
```python
    def install(self, log=print, url=None):
        return store.pull(self.meta, self.config, log=log, url=url)
```

**local_faster_whisper.py / local_whispercpp.py / local_transformers.py** — 各自 `install` 签名加 `url=None`(忽略,这些引擎不走 URL 下载):把 `def install(self, log=print) -> str:` 改为 `def install(self, log=print, url=None) -> str:`(函数体不变)。

**api.py** — `pull` 透传:
```python
def pull(model, *, config=None, url=None, log=print):
    """安装一个模型/引擎(本地下载权重或引擎;云端无需)。url 可覆盖默认下载地址。返回位置。"""
    return registry.make_adapter(model, config or {}).install(log=log, url=url)
```

**cli.py** — `pull` 子命令加 `--url` 并透传。把
```python
    pp = sub.add_parser("pull", help="download a local model")
    pp.add_argument("model")
```
改为:
```python
    pp = sub.add_parser("pull", help="download a local model")
    pp.add_argument("model")
    pp.add_argument("--url", default=None,
                    help="download from this URL instead of the model's default (http/https)")
```
并把 pull 分支的 `d = api.pull(a.model)` 改为 `d = api.pull(a.model, url=a.url)`。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `PYTHONPATH=src python -m pytest tests/ -o addopts="" -q`
Expected: PASS(既有 + 新增全绿;e2e skip)

- [ ] **Step 5: 提交**

```bash
git add src/asrkit/types.py src/asrkit/store.py src/asrkit/api.py src/asrkit/cli.py src/asrkit/adapters/local_sherpa.py src/asrkit/adapters/local_faster_whisper.py src/asrkit/adapters/local_whispercpp.py src/asrkit/adapters/local_transformers.py tests/test_smoke.py
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "feat(pull): --url 一次性下载覆盖(经 install 边界透传,限 http/https)"
```

---

## Task 5: 文档 — usage + CHANGELOG

**Files:**
- Modify: `docs/usage.md`、`CHANGELOG.md`

- [ ] **Step 1: 更新 `docs/usage.md`**

加一小节说明:
- `asrkit pull <model> --url <tarball>`:从自定义地址下(http/https;格式按内容自动识别)。
- **HF 系引擎镜像**:faster-whisper/transformers/whispercpp 设 `HF_ENDPOINT=https://hf-mirror.com` 即走镜像(底层库处理,asrkit 无需配置)。
- **云端重试**:云端调用自动重试瞬时故障;`ASRKIT_HTTP_RETRIES`(默认 3)可调。**成本安全**:计费的转写请求只在限流(429)/连接未建立时重试,读超时/5xx 不重试(避免重复计费);doubao 轮询(只读)重试全部。

- [ ] **Step 2: 追加 `CHANGELOG.md`(不改版本号)**

在 `## [Unreleased]` 节(若无则在最新版本节之上新建)追加:
```markdown
### 新增
- **云端重试**:云端 adapter 走共享 Session + 分级重试/退避(`asrkit/_http.py`)。计费转写请求只重试 429/连接未建立(读超时/5xx 不重,避免重复计费);doubao 轮询(只读)重试全部。`ASRKIT_HTTP_RETRIES` 可调(默认 3)。doubao 改用 uuid 幂等 `X-Api-Request-Id`。
- **`asrkit pull --url`**:从自定义地址下载(限 http/https;格式按内容识别)。HF 系引擎镜像用 `HF_ENDPOINT`(零配置)。
- openai/elevenlabs 上传补 200MB 大小守卫(与 dashscope/doubao 对齐)。
```

- [ ] **Step 3: 提交**

```bash
git add docs/usage.md CHANGELOG.md
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "docs(w2): 云端重试/pull --url/HF_ENDPOINT 用法 + CHANGELOG"
```

---

## Task 6: 收尾验证(ruff/mypy/全量)

**Files:** 无(纯验证)

- [ ] **Step 1: lint + 类型 + 全量测试**

Run:
```
ruff check src tests
mypy
PYTHONPATH=src python -m pytest tests/ -o addopts="" -q
```
Expected: ruff All checks passed;mypy Success;pytest 全绿(新增 test_http/test_cloud_retry + 既有;e2e skip)。

- [ ] **Step 2: 若有 lint/type 报错,inline 修掉后重跑**

常见:未用 import、`Optional` 标注、`_http.post` 返回类型。修到全绿。

- [ ] **Step 3: 提交(若 Step 2 有修改)**

```bash
git add -u
git -c user.name="BolynWang" -c user.email="lm2039136@gmail.com" commit -m "chore(w2): lint/type 收尾"
```

---

## Self-Review 记录

- **Spec 覆盖**:_http 线程局部 Session + 分级重试(T1);doubao uuid+策略(T2);openai/elevenlabs/dashscope 路由+守卫(T3);pull --url 经 install 边界(T4);docs+HF_ENDPOINT+ASRKIT_HTTP_RETRIES(T5);验证(T6)。✅
- **成本安全**:计费 POST 仅重 429+ConnectTimeout,由 `_BILLABLE_STATUS={429}` + 异常分支保证(T1),并被 T1 的 `test_billable_does_not_retry_500`/`test_read_timeout_not_retried_billable` 钉死。
- **类型一致**:`_http.post(url, *, idempotent, retries, **kwargs)`、`_retries/_backoff/_retry_after/_sleep/_session`、`store.pull(..., *, url=None)`、`install(self, log=print, url=None)`、`api.pull(model, *, config=None, url=None, log=print)` 全任务一致。
- **请求形状不变**:各 adapter 仅把 `requests.post`→`_http.post` 并加 `idempotent`;headers/body/data/files 语义不变(openai/elevenlabs 的 files 从句柄改 `(basename, bytes)` 是可重试必需,内容等价)。
