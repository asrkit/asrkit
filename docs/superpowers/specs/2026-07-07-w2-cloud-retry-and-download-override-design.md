# W2 设计 — 云端重试 + 下载源可自定义(极简)

> 状态:已通过分析对齐(用户"按推荐"),待写实现计划。
> 目标波次:W2(见 [roadmap.md](../../roadmap.md))。落地默认下个 PATCH,升号前问人类。
> 定位约束:守住"接口内核极薄"、**零新增运行时依赖**(`requests` 自带即可)。

---

## 1. 背景与目标

两件"HTTP 健壮性/灵活性",合成一个 W2:

1. **云端重试(主菜)**:5 个云端 adapter 现在都是一次性 `requests.post`,`status>=300` 直接失败——无 Session、无重试、无退避。W1 的**批量转写**让这个短板暴露:`transcribe *.wav -m dashscope/... --batch` 顺序打上百个请求,几乎必然撞 429 限流 → 随机文件失败。加共享 Session + 重试/退避,批量+云端(asrbench 核心场景)才可靠。
2. **下载源可自定义(极简附带)**:sherpa 模型由 asrkit 自己从 GitHub release 下(URL 写死);让用户能一次性换源。**不做**持久化镜像配置(那是"镜像"本体,网络问题用户自解决,YAGNI)。

**澄清**:"下载源可切"和"镜像"是同一个问题(从别处下)。HF 系引擎(faster-whisper/transformers/whispercpp)的镜像由底层库的 `HF_ENDPOINT` 自动处理,asrkit **零代码**;只有 sherpa 那半需要 asrkit 自己给个口子——且只做最轻的一次性 `--url`。

---

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 下载源 | 只加一次性 `asrkit pull <model> --url <tarball>`;**不做** `download-base`/持久镜像配置 |
| D2 | HF 镜像 | 文档说明 `HF_ENDPOINT` 直接生效,**零代码** |
| D3 | 云端重试实现 | 共享 `requests.Session` + **手写重试循环**(易测、精确控制),放新模块 `asrkit/_http.py`,零新依赖 |
| D4 | 重什么 | 重:`{429,500,502,503,504}` + **连接类错误**(ConnectError/ConnectTimeout/ConnectionError,服务端没收到=安全)。不重:其它 4xx |
| D5 | **读超时** | **默认不重试**(服务端可能已处理,重试会重复转写/双扣费,尤其 doubao submit);仅连接类超时重 |
| D6 | 退避 | 指数退避+抖动(base 0.5s ×2,封顶 8s,默认 3 次);429 尊重 `Retry-After` 头 |
| D7 | 配置 | 仅 `ASRKIT_HTTP_RETRIES` 环境变量(默认 3);退避参数写死。不做一堆旋钮 |
| D8 | 上传体 | 文件先**读成 bytes** 再发(≤200MB 已有上限),使重试可安全重发(openai/elevenlabs 改;dashscope/doubao 已是 base64 body) |

---

## 3. 设计

### 3.1 云端重试 `asrkit/_http.py`(新)

一个进程级共享 Session + 手写重试的 POST 助手,5 个 adapter + doubao 都改走它。

**接口**
```
post(url, *, retries=None, timeout=..., **kwargs) -> requests.Response
```
- `_session()`:惰性建单例 `requests.Session()`(连接池复用;serve/批量受益,urllib3 连接池线程安全)。
- 重试循环(伪码):
  ```
  n = retries if retries is not None else int(os.environ.get("ASRKIT_HTTP_RETRIES", "3"))
  for attempt in range(n + 1):
      try:
          r = _session().post(url, **kwargs)
      except (ConnectionError, ConnectTimeout) as e:   # 连接类:服务端没收到 → 安全重试
          if attempt == n: raise
          _sleep(_backoff(attempt)); continue
      except ReadTimeout:                              # 读超时:可能已处理 → 不重试(防双扣费)
          raise
      if r.status_code in {429,500,502,503,504} and attempt < n:
          _sleep(_retry_after(r) or _backoff(attempt)); continue
      return r
  ```
  - `_backoff(attempt)` = `min(0.5 * 2**attempt, 8) * (1 + jitter)`。
  - `_retry_after(r)`:解析 `Retry-After` 头(秒),封顶(如 30s),无则 None。
  - `_sleep` 单列成模块函数,便于测试 monkeypatch(不真睡)。
- **异常语义不变**:最终仍可能抛(连接错重试耗尽)或返回错误响应;各 adapter 的 `try/except` 与 `status>=300` 处理**保持原样**,只是中间多了重试。

**各 adapter 改动(请求形状一字不改,只把 `requests.post` 换成 `_http.post`)**
- `cloud_openai` / `cloud_elevenlabs`:上传从 `files={"file": f}`(开着的句柄)改为先 `data=f.read()` 成 bytes、`files={"file": (basename, data)}`,再 `_http.post`。
- `cloud_dashscope._post` / `cloud_doubao`(submit + 每次 query):`requests.post` → `_http.post`。doubao 轮询循环逻辑不变;submit 与每个 query 各自获得重试(submit 因幂等风险只重连接类/5xx/429,不重读超时——正好由 D5 覆盖)。

### 3.2 下载源一次性覆盖(极简)

- `asrkit pull <model> --url <tarball>`:`--url` 存在时,`pull` 用它替代 `meta.download_url`(内容格式仍按 magic bytes 自动识别,复用已有多格式解压)。
- 线程:`cli pull` → `api.pull(model, *, url=None)` → `store.pull(meta, config, *, url=None)`;`url` 优先于 `meta.download_url`。
- 仅本地模型可 pull(现有校验不变);`--url` 对无默认 URL 的已注册模型也可用(等于补上地址)。
- **不加** config/env 的 `download-base`。`add-model --url` 保持不变。

---

## 4. 契约/行为影响

- **对成功路径零影响**:重试只在失败时介入;成功响应逐字不变。退出码/输出契约(W1)不变。
- **延迟**:瞬时故障时增加有界延迟(最坏 ≈ 0.5+1+2 ≈ 3.5s×… 封顶,3 次)。正常无感。
- **成本安全**:读超时不重试 → 不会因超时重复计费/重复建 doubao 任务。
- `pull --url` 是**新增**旗标,不影响旧调用。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/_http.py` | **新增**:共享 Session + `post()` 重试助手 + `_backoff`/`_retry_after`/`_sleep` |
| `asrkit/adapters/cloud_openai.py` | `requests.post`→`_http.post`;上传改 bytes |
| `asrkit/adapters/cloud_elevenlabs.py` | 同上 |
| `asrkit/adapters/cloud_dashscope.py` | `_post` 走 `_http.post` |
| `asrkit/adapters/cloud_doubao.py` | submit + query 走 `_http.post` |
| `asrkit/store.py` | `pull(meta, config, *, url=None)` 支持 URL 覆盖 |
| `asrkit/api.py` | `pull(model, *, config=None, url=None, log=print)` 透传 |
| `asrkit/cli.py` | `pull` 子命令加 `--url`;调 `api.pull(..., url=a.url)` |
| `docs/usage.md` | 记 `pull --url`、`HF_ENDPOINT`、`ASRKIT_HTTP_RETRIES` |
| `CHANGELOG.md` | `[Unreleased]` 追加(版本号等人类定) |

---

## 6. 测试

- **`test_http.py`(新,mock `_http._session().post`,零真实网络)**:
  - 429→429→200:重试 2 次后成功,返回 200。
  - 3×500:重试耗尽,返回最后的 500 响应(不抛)。
  - 抛 `ConnectionError` 2 次再成功:重试后成功。
  - 抛 `ReadTimeout`:**立即抛出,不重试**(断言 `session.post` 只被调 1 次)。
  - `400`:不重试(只调 1 次)。
  - `429` 带 `Retry-After: 1`:`_sleep` 收到 ~1;`_sleep` 被 monkeypatch 不真睡。
  - `ASRKIT_HTTP_RETRIES=0`:不重试。
- **adapter 层**:mock `_http.post` 返回假响应,断言 openai/dashscope/doubao/elevenlabs 仍正确解析(请求形状不变);断言上传体已是 bytes(可重发)。
- **`store` / `pull --url`**:`store.pull(meta, config, url=<自建 tar>)` 用覆盖 URL(mock `_download` 或用本地 file:// / 直接塞临时 tar 走 `_extract_archive`);断言 `meta.download_url` 被忽略。
- **回归**:现有全部测试仍绿;云端 adapter 的既有冒烟/构造测试不受影响。

---

## 7. 明确不做(YAGNI)

- 持久化 `download-base` / 镜像配置(D1)。
- HF_ENDPOINT 相关代码(D2,底层库已管)。
- 断点续传下载(独立后续项)。
- 读超时重试(D5,双扣费风险)。
- 一堆重试旋钮(D7,只留 `ASRKIT_HTTP_RETRIES`)。
- 并发批量(批量仍顺序;顺序天然给限流退避留空间,不做并发)。

---

## 8. 风险与兼容

- **最大风险 = 动了作者真机接通过的 5 个云端 adapter**。缓解:**请求形状逐字不变**,只把 `requests.post` 换成透明的 `_http.post`;全程 mock 测试、不打真实 API;成功路径零改变。
- 上传改 bytes:openai/elevenlabs 失去流式上传,但文件有 200MB 上限、本就不大,换来可安全重试,值得。
- 读超时不重试是**有意为之**(成本安全);文档写明"若宁可多花钱也要成功,可后续加开关"——现在不做。
- `pull --url`、`ASRKIT_HTTP_RETRIES` 均为新增,向后兼容。
