# 设计 — 长跑健壮性修复(doubao 轮询上限 + serve 缓存无界)

> 状态:brainstorming 完成、用户批准默认值、**Codex(gpt-5.5)评审采纳 3 项 → v2**,待写实现计划。
>
> **v2 修订**(Codex `.omc/artifacts/ask/codex-*2026-07-08T02-02-54*.md`):
> 1. **deadline 不溢出**:原循环 sleep 后仍会发一次 query,叠加 `_http` 重试可远超配置超时。→ 改 remaining-based:每轮先算 `remaining = deadline - now`,`remaining<=0` 即 break,`sleep(min(interval, remaining))`,不在 deadline 之后再排新 query(残留仅"一次在途 query 自身 timeout=60",诚实且有界)。
> 2. **缓存双建竞态**:`make_adapter` 在锁外,重入锁后**必须再查一次**缓存,命中则返回已有——否则并发同 model miss 会用冷 adapter 覆盖热的、返回分裂对象(本地模型 lazy load 时尤其咬人)。
> 3. **非有限浮点**:`_poll_timeout_s` 用 `math.isfinite(v) and v > 0`,挡 `ASRKIT_DOUBAO_POLL_TIMEOUT_S=inf` 导致的无限轮询。
> 波次:专家评审遗留的两颗"看着能用实则炸"的炸弹;落地默认下个 PATCH,**升号先问人类**。
> 定位约束:纯 bug 修复 + 向后兼容(新增 env 旋钮,默认行为更健壮);不碰契约、不加运行时依赖。

---

## 1. 背景与目标

两处长跑场景下的隐性失败,专家评审点名:
1. **doubao 轮询硬上限 30s**(`adapters/cloud_doubao.py:71`):`for _ in range(30): time.sleep(1)` —— 长音频异步识别一旦 >30s **必然** `doubao polling timeout (30s)`,对长文件全废。
2. **serve adapter 缓存无界**(`server.py:22`):`_ADAPTERS: dict = {}` 每个请求过的 model 永久缓存;本地 adapter 持有已加载模型(`self._rec`),长跑服务内存**无界增长**。

目标:两处都改成有界/可配,默认更健壮,均向后兼容。

---

## 2. 已定决策(用户批准)

| # | 决策 | 取值 |
|---|---|---|
| D1 | doubao 轮询总超时默认 | **300s**;env `ASRKIT_DOUBAO_POLL_TIMEOUT_S` 覆盖 |
| D2 | doubao 轮询间隔 | 轻微退避 1s → 5s 上限(减少长任务 query 洪水) |
| D3 | serve 缓存策略 | 有界 **LRU**,默认容量 **8**;env `ASRKIT_SERVE_CACHE` 覆盖 |
| D4 | 缓存实现 | 手写 `OrderedDict` + 锁(比 `lru_cache` 可测、可控容量、保留"并发首次各建一次无害"语义) |
| D5 | 不做 | 按音频时长动态定超时(内核不解码,YAGNI);缓存 TTL/主动 close(GC 释放即可) |

---

## 3. 设计

### 3.1 doubao 轮询(`adapters/cloud_doubao.py`)

`os`、`time` 已 import(`os.path.getsize`、`time.sleep` 在用)。加模块级 helper + 改轮询循环(submit 段不动):

需 `import math`(`os`、`time` 已 import)。

```python
def _poll_timeout_s() -> float:
    """轮询总超时(秒)。env ASRKIT_DOUBAO_POLL_TIMEOUT_S 覆盖,非法/非有限/<=0 回退默认。"""
    raw = os.environ.get("ASRKIT_DOUBAO_POLL_TIMEOUT_S")
    if raw:
        try:
            v = float(raw)
            if math.isfinite(v) and v > 0:     # v2:挡 inf/nan 导致无限轮询
                return v
        except ValueError:
            pass
    return 300.0
```

轮询段(替换现 `for _ in range(30): ...` 到 `return ... timeout (30s)`),**remaining-based,不在 deadline 后再排 query**:

```python
            poll_timeout = _poll_timeout_s()
            deadline = time.perf_counter() + poll_timeout
            interval = 1.0
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:                        # v2:到点即停,不再排新 query
                    break
                time.sleep(min(interval, remaining))       # v2:不 sleep 过 deadline
                q = _http.post(f"{base}/query", headers=headers, data="{}",
                               timeout=60, idempotent=True)
                code = q.headers.get("x-api-status-code", "")
                if code == "20000000":
                    j = q.json()
                    text = (j.get("result") or {}).get("text") or j.get("text", "")
                    return TranscribeResult(
                        text=(text or "").strip(),
                        latency_ms=int((time.perf_counter() - t0) * 1000), raw_response=j)
                if code.startswith("45") or code.startswith("55"):
                    return TranscribeResult(text="", error=f"query failed code={code}: {q.text[:200]}")
                interval = min(interval * 1.5, 5.0)         # 轻微退避,上限 5s
            return TranscribeResult(
                text="", error=f"doubao polling timeout ({int(poll_timeout)}s)")
```

- 只读轮询(`idempotent=True`),不涉重复计费。
- 超时消息报**实际**超时值(`int(poll_timeout)`)。
- 退避从 1s 起,×1.5 到 5s 上限:短任务仍 ~1s 响应,长任务 query 次数大降。
- **不溢出**:每轮先算 `remaining`,`<=0` 即 break、`sleep` 不超 `remaining`,故 deadline 之后不再排新 query。残留仅"最后一次在途 query 自身 `timeout=60` + `_http` 重试"这一 HTTP 调用边界,不可完全消除但有界(单次调用)。

### 3.2 serve 缓存(`server.py`)

替换 `_ADAPTERS: dict = {}` 与 `_get_adapter`。加 `os`(已 import)、`threading`、`collections.OrderedDict`:

```python
import threading
from collections import OrderedDict

# 已加载 adapter 的有界 LRU 缓存,避免每请求重载本地模型 + 防长跑内存无界。
# 单进程内存缓存;同模型并发首次可能各建一次(在锁外 make),无害。
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
            _ADAPTERS.move_to_end(model)     # 命中 → 最近使用
            return a
    a = registry.make_adapter(model)         # 锁外(可能慢/可能抛 ModelNotFoundError)
    with _CACHE_LOCK:
        existing = _ADAPTERS.get(model)      # v2:重入锁后再查,防并发双建覆盖热 adapter
        if existing is not None:
            _ADAPTERS.move_to_end(model)
            return existing                  # 丢弃刚建的冷 a,返回已有热的(对象一致)
        _ADAPTERS[model] = a
        _ADAPTERS.move_to_end(model)
        while len(_ADAPTERS) > _cache_size():
            _ADAPTERS.popitem(last=False)     # 淘汰最久未用;被淘汰 adapter 由 GC 释放模型内存
    return a
```

- **异常不入缓存**:`make_adapter` 抛 `ModelNotFoundError` 在存入前,坏 model 不毒化缓存(与今天行为一致)。
- **并发双建收敛**(v2):同 model 并发 miss 仍可能各建一次(锁外),但重入锁后**只留一个、都返回同一对象**;多余的冷 adapter 被丢弃、GC 回收。本地模型 lazy load(sherpa/faster-whisper 在 `transcribe` 才真加载),故重复 make 的成本主要是对象构造而非模型权重,代价可控。
- **容量每次插入时读**:`_cache_size()` 每次插入求值 → 测试可 monkeypatch env 或该函数控制容量。
- 命中在锁内 `move_to_end`,维持 LRU 顺序;线程安全。
- `transcriptions` 端点调用点不变(仍 `adapter = _get_adapter(model)`,404 分支不变)。

---

## 4. 契约/行为影响

- **纯 bug 修复**:无契约变更、无 CLI/API 签名变更、无新运行时依赖(`threading`/`collections`/`functools` 皆标准库)。
- 行为变更均**更健壮**:doubao 长音频不再 30s 截断;serve 内存有界。默认关(env 不设)即得新默认值。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `src/asrkit/adapters/cloud_doubao.py` | 加 `_poll_timeout_s()`;轮询循环改 deadline + 退避 |
| `src/asrkit/server.py` | `_ADAPTERS` 改有界 LRU;加 `_cache_size()`、`_CACHE_LOCK` |
| `tests/test_cloud_retry.py` 或新 `tests/test_doubao_poll.py` | doubao 轮询:迟到成功不截断 + 超时可配 |
| `tests/test_serve.py` | serve 缓存:命中/未命中/有界淘汰/LRU 顺序 |
| `docs/usage.md` / `CHANGELOG.md` | 两个 env 旋钮 + `[Unreleased]` |

---

## 6. 测试

### doubao(mock `_http.post` + `time.sleep` noop)
- **迟到成功不再 30s 截断**:`monkeypatch cloud_doubao.time.sleep` → noop;`_http.post` 打桩:`/submit` 返回 status 200;`/query` 前 K 次返回"处理中"状态码(如 `""` 或非终态)、第 K+1 次返回 header `x-api-status-code="20000000"` 且 `.json()` 带 text。断言返回该 text(非 timeout),即便 K 远大于 30(证明不再受 30 次硬限)。
- **超时可配 + 消息报实际值**:`monkeypatch cloud_doubao.time.sleep` → noop,并 `monkeypatch cloud_doubao.time.perf_counter` 用递增桩(如每次调用 +100)使 deadline 很快被跨过;`/query` 恒"处理中";`monkeypatch _poll_timeout_s`→返回如 120。断言返回 `error` 含 `"doubao polling timeout (120s)"`。
- **终态错误码提前返回**:`/query` 返回 `45xxx` → 立即 `query failed`,不等超时。
- **非法/非有限 env 回退默认(v2)**:`ASRKIT_DOUBAO_POLL_TIMEOUT_S` 设 `"inf"`/`"nan"`/`"abc"`/`"0"`/`"-5"` → `_poll_timeout_s()` 均返回 `300.0`(单元测该 helper,不跑真轮询)。

### serve(mock `registry.make_adapter`)
- **命中不重建**:`monkeypatch server.registry.make_adapter` 计数并每次返回新哨兵;先 `_get_adapter("m")` 两次 → make 只调 1 次、两次返回同一对象。测试前后 `_ADAPTERS.clear()` 保证隔离。
- **有界淘汰 + LRU 顺序**:`monkeypatch server._cache_size`→返回 2;`_get_adapter("A")`、`"B"`、`"C"` → `_ADAPTERS` 只剩 2 项且不含 `"A"`(最久未用被淘汰);再 `_get_adapter("A")` → make 再次被调(已淘汰,cache miss)。
- **命中刷新 LRU**:size=2;A、B、访问 A(命中)、再 C → 被淘汰的是 B(A 因命中而最近),断言 `"A" in _ADAPTERS and "B" not in _ADAPTERS`。
- **异常不入缓存**:`make_adapter` 抛 `ModelNotFoundError` → `_get_adapter` 抛同异常且 `_ADAPTERS` 不含该 key。
- **回归**:现有 serve 测试仍绿。

---

## 7. 明确不做(YAGNI)

按音频时长动态定超时;缓存 TTL / 主动 `close()` / 显式模型卸载;doubao 轮询并发化;serve 多进程共享缓存。

---

## 8. 风险与兼容

- 纯只读/内存层改动,回归面小。
- doubao:退避使长任务 query 次数从"每秒一次"降到稀疏;最坏单请求占线程 ~300s(线程池内,已有 `run_in_threadpool` 隔离)。
- serve:锁仅护内存字典 O(1) 操作,不含 `make_adapter`(慢/可能抛),不阻塞事件循环。
