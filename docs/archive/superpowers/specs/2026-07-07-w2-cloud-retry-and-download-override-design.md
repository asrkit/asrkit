# W2 设计 v2 — 云端重试 + 下载源可自定义(含 Codex 评审修订)

> 状态:分析对齐 + Codex(gpt-5.5)评审(采纳 8 项),待写实现计划。
> 目标波次:W2。落地默认下个 PATCH,升号前问人类。
> 定位约束:守住"接口内核极薄"、**零新增运行时依赖**(`requests` 自带)。
>
> **v2 修订**:Codex 评审 `.omc/artifacts/ask/codex-*2026-07-07T08-08-09*.md`。核心变更:**每调用重试策略**(计费 POST vs 只读)、doubao 用 uuid 幂等键、线程局部 Session、Retry-After 双格式、上传守卫补全、install 边界透传 url、env 安全解析。

---

## 1. 背景与目标

1. **云端重试(主菜)**:5 个云端 adapter 现为一次性 `requests.post`,无 Session/重试/退避。W1 批量转写顺序打上百请求 → 撞 429 限流即随机失败。加共享 Session + 重试/退避。
2. **下载源可自定义(极简)**:只加一次性 `asrkit pull <model> --url`;不做持久镜像配置;HF 系用 `HF_ENDPOINT`(底层库自理,零代码)。

---

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 下载源 | 仅 `asrkit pull <model> --url <tarball>`(**限 http/https**);不做 `download-base` |
| D2 | HF 镜像 | 文档说明 `HF_ENDPOINT`,零代码 |
| D3 | 实现 | 手写重试循环 + **线程局部** `requests.Session`,放 `asrkit/_http.py`,零新依赖 |
| **D4** | **重试范围(每调用策略)** | **计费 POST**(转写/doubao submit):只重 `429` + `ConnectTimeout`。**只读**(doubao query 轮询):重 `429`+`{500,502,503,504}`+所有连接/超时 |
| D5 | 读超时 & 泛连接错 | 计费 POST **不重** `ReadTimeout`、泛 `ConnectionError`、其它 `5xx`(任一都可能发生在**已计费**之后);只读调用才重 |
| D6 | doubao 幂等 | `X-Api-Request-Id` 改 `uuid4`,**submit 与其所有 query 复用同一个**(Volcengine 以此为任务 id/幂等键) |
| D7 | 退避 | 指数退避+抖动(base 0.5s ×2,**抖动后** clamp ≤8s,默认 3 次);429 认 `Retry-After`(秒或 HTTP-date),clamp 0..30s |
| D8 | 配置 | 仅 `ASRKIT_HTTP_RETRIES`(默认 3,**非法输入回退默认、clamp 0..10**) |
| D9 | 上传体 | openai/elevenlabs 先读 bytes(**并补 200MB 守卫**,现无),`files={"file": (basename, data)}`;dashscope/doubao 已是 base64 body |
| D10 | Session | **线程局部**(`threading.local`),避免 serve 线程池并发下 requests.Session 的 cookie/header 可变共享 |

---

## 3. 设计

### 3.1 `asrkit/_http.py`(新)

**接口**
```
post(url, *, idempotent=False, retries=None, timeout=..., **kwargs) -> requests.Response
```

- **线程局部 Session**:`_local = threading.local()`;`_session()` 惰性建 `_local.session = requests.Session()`,可 `mount` 一个 `HTTPAdapter(pool_maxsize=…)`。每线程一个,serve 并发安全。
- **重试次数**:`_retries()` 安全解析 `ASRKIT_HTTP_RETRIES`(默认 3;`ValueError`/负数 → 默认;clamp 0..10)。
- **重试循环**(异常捕获顺序关键——`ConnectTimeout` 是 `ConnectionError`+`Timeout` 的子类,`ReadTimeout` 是 `Timeout` 子类):
  ```
  for attempt in range(n + 1):
      try:
          r = _session().post(url, timeout=timeout, **kwargs)
      except ConnectTimeout:                 # 从未到达服务端 → 计费/只读都安全重
          if attempt == n: raise
          _sleep(_backoff(attempt)); continue
      except ReadTimeout:                     # 服务端可能已处理 → 仅只读重
          if idempotent and attempt < n:
              _sleep(_backoff(attempt)); continue
          raise
      except ConnectionError:                 # 泛(含 ProtocolError/OSError,可能已发出) → 仅只读重
          if idempotent and attempt < n:
              _sleep(_backoff(attempt)); continue
          raise
      except Timeout:                         # 泛超时 → 仅只读重
          if idempotent and attempt < n:
              _sleep(_backoff(attempt)); continue
          raise
      retry_codes = {429, 500, 502, 503, 504} if idempotent else {429}
      if r.status_code in retry_codes and attempt < n:
          _sleep(_retry_after(r) or _backoff(attempt)); continue
      return r
  ```
- `_backoff(attempt)` = `min(0.5 * 2**attempt, 8)`,乘 `(1 + random.uniform(0, 0.25))`,**最后再 clamp ≤ 8s**。
- `_retry_after(r)`:头存在时,先试 `int(秒)`;否则 `email.utils.parsedate_to_datetime` 解 HTTP-date → 距今秒数;clamp `0..30`;无/解析失败 → None。
- `_sleep(s)`:`time.sleep` 薄封装(测试 monkeypatch,不真睡)。
- **异常/错误语义不变**:最终仍可能抛或返回错误响应;各 adapter 的 `try/except` + `status>=300` 处理**原样保留**。

### 3.2 云端 adapter 改动(请求形状逐字不变,仅换传输)

- **cloud_openai / cloud_elevenlabs**:
  ```
  sz = os.path.getsize(path)
  if sz > 200*1024*1024: return TranscribeResult(error="audio is {}MB, over 200MB ...")
  with open(path, "rb") as f: data = f.read()
  _http.post(url, ..., files={"file": (os.path.basename(path), data)}, idempotent=False)
  ```
  (新增 size 守卫——这两家原本没有,与 dashscope/doubao 对齐。)
- **cloud_dashscope `_post`**:`requests.post` → `_http.post(url, ..., idempotent=False)`(已有 base64 body + 200MB 守卫)。
- **cloud_doubao**:
  - `req_id = str(uuid.uuid4())`(一次生成),`X-Api-Request-Id` 用它;submit 与每次 query **同一个**。
  - submit:`_http.post(f"{base}/submit", ..., idempotent=False)`(只重 429+ConnectTimeout;uuid 幂等键额外兜底)。
  - query 轮询:`_http.post(f"{base}/query", ..., idempotent=True)`(只读,重全部);轮询循环逻辑不变。

### 3.3 下载源一次性覆盖

- `asrkit pull <model> --url <tarball>`。
- 透传链(经真实安装边界):
  - `cli pull` → `api.pull(a.model, url=a.url)`。
  - `api.pull(model, *, config=None, url=None, log=print)` → `adapter.install(log=log, url=url)`。
  - `BaseAdapter.install(self, log=print, url=None)`:签名加 `url`(base/云端忽略)。各本地引擎 install 同加 `url=None`;仅 `SherpaLocal.install` 透传给 `store.pull`。
  - `store.pull(meta, config=None, log=print, *, url=None)`:`effective_url = url or meta.download_url`,在"无 URL"检查/日志/下载处一律用它。
- **限 http(s)**:`url` 非 `http://`/`https://` 开头 → `ValueError`(不放 file://、ftp)。已有 tar/zip 防穿越 + 内容识别继续保护。**serve 永不暴露此覆盖**(它只在 CLI）。

---

## 4. 契约/行为影响

- **成功路径零改变**;退出码/输出契约(W1)不变。
- **成本安全强化**:计费 POST 只在"服务端明确拒绝(429)/根本没到达(ConnectTimeout)"时重 → 零双扣费。
- 瞬时故障时延迟有界(最坏 ≈ 3 次退避,≤ ~24s)。
- `pull --url`、`ASRKIT_HTTP_RETRIES` 均新增,向后兼容。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/_http.py` | **新增**:线程局部 Session + `post(idempotent=...)` + `_backoff`/`_retry_after`/`_sleep`/`_retries` |
| `asrkit/adapters/cloud_openai.py` | `_http.post`;读 bytes + basename + **200MB 守卫**;`idempotent=False` |
| `asrkit/adapters/cloud_elevenlabs.py` | 同上 |
| `asrkit/adapters/cloud_dashscope.py` | `_post` → `_http.post(idempotent=False)` |
| `asrkit/adapters/cloud_doubao.py` | uuid request-id 复用;submit `idempotent=False` / query `idempotent=True` |
| `asrkit/types.py` | `BaseAdapter.install(self, log=print, url=None)` 加 `url` |
| `asrkit/adapters/local_sherpa.py` | `install(url=None)` 透传 store.pull;其余本地引擎 install 加 `url=None`(忽略) |
| `asrkit/store.py` | `pull(..., *, url=None)`:`effective_url`;http(s) 限制 |
| `asrkit/api.py` | `pull(model, *, config=None, url=None, log=print)` 透传 |
| `asrkit/cli.py` | `pull` 加 `--url`;调 `api.pull(..., url=a.url)` |
| `docs/usage.md` | `pull --url`、`HF_ENDPOINT`、`ASRKIT_HTTP_RETRIES`、重试语义(计费只重 429/连接) |
| `CHANGELOG.md` | `[Unreleased]` 追加 |

---

## 6. 测试(全程 mock,零真实网络)

- **`test_http.py`(新,mock `_http._session().post` 或注入假 session)**:
  - `429→429→200`:计费重 2 次后成功。
  - `429`(billable):重;`500/502/503/504`(billable):**不重**(只调 1 次,返回该响应)。
  - `500`(idempotent=True):重;耗尽返回最后 500。
  - 抛 `ConnectTimeout`:计费也重(2 次后成功)。
  - 抛 `ReadTimeout`(billable):**立即抛,只调 1 次**;`ReadTimeout`(idempotent):重。
  - 抛泛 `ConnectionError`(billable):不重;(idempotent):重。
  - `Retry-After: 3`(秒)与 `Retry-After: <HTTP-date>`:`_sleep` 收到对应秒数(monkeypatch 不真睡),clamp 0..30。
  - `ASRKIT_HTTP_RETRIES` 非法/`-1`/`0`:回退默认 / clamp / 不重。
  - `_backoff` 抖动后 ≤ 8s。
- **adapter 层(mock `_http.post`)**:断言 openai/elevenlabs 的 `files` kwarg 是 `(basename, bytes)`;断言 doubao submit 用 `idempotent=False`、query 用 `idempotent=True`、submit/query 同一 request-id;各家解析仍正确;openai/elevenlabs 超 200MB 友好报错。
- **store/pull --url**:`store.pull(meta, config, url=<临时 tar>)` 覆盖 `meta.download_url`;非 http(s) URL 抛 `ValueError`。
- **回归**:现有全部测试仍绿。

---

## 7. 明确不做(YAGNI)

- 持久 `download-base`/镜像配置、HF_ENDPOINT 代码、断点续传。
- 计费 POST 重 5xx/读超时(D4/D5,成本安全)。
- 一堆重试旋钮(仅 `ASRKIT_HTTP_RETRIES`)。
- 并发批量(顺序天然给限流退避留空间)。
- 通过 serve 暴露 `--url`(SSRF 面,永不)。

---

## 8. 风险与兼容

- **最大风险 = 动了作者真机接通过的 5 个云端 adapter**。缓解:**请求形状逐字不变**,只换 `requests.post`→`_http.post`;全程 mock 测试;成功路径零改变。
- 上传改 bytes:requests **今天本就把句柄读进内存**(非真流式),故不损失流式;换来可安全重发;openai/elevenlabs 顺带补上原缺的 200MB 守卫。
- **计费 POST 保守重试**(只 429+ConnectTimeout)是有意为之——可用性略降、成本安全拉满,符合成本优先;文档写明"若宁可多花钱也要成功,可后续放宽 idempotent 策略"。
- doubao uuid 幂等键:即便未来放宽 submit 重试,重放同 id 也由服务端去重兜底。
- 线程局部 Session:serve 线程池下各线程独立,无 cookie/header 竞争。
