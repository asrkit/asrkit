# 设计 — `--verbose` / 日志(P3)

> 状态:brainstorming 完成、用户批准(等级模型 `-v/-vv` 计数;埋点三处全做),待 Codex 评审 → 实现计划。
> 定位约束:引入标准库 `logging`;**作为库 import 零副作用**(NullHandler);日志是**补充**,现有面向用户的 `[error]`/`[warn]` print 保持不变。零新依赖。

---

## 1. 背景

全项目无 `logging`,信息全靠 `print`/`result.error`。痛点:`_http` 重试**完全静默**(看不出"为啥慢/在不在重试");serve 只有一句 raw print 记错误,长跑排障难。加分级日志 + `-v` 开关。

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 等级模型 | `-v`=INFO,`-vv`=DEBUG(`action="count"` 默认 0);默认 WARNING(静默) |
| D2 | 埋点 | `_http` 重试(INFO)+ serve 请求/错误(INFO)+ CLI 转写 adapter/metrics(DEBUG) |
| D3 | 库安全 | `logging.getLogger("asrkit")` 挂 `NullHandler`;import 不刷屏;仅 `setup()` 点亮 stderr |
| D4 | 不做 | 结构化 JSON 日志、落文件、第三方框架、把每个 print 都改 logger |

## 3. 设计

### 3.1 `asrkit/log.py`(新)

```python
"""集中日志:作为库导入零副作用(NullHandler);CLI 用 setup() 点亮 stderr。"""
from __future__ import annotations

import logging
import sys
from typing import Optional

_NAME = "asrkit"
logging.getLogger(_NAME).addHandler(logging.NullHandler())   # 库安全:import 不刷屏

_HANDLER: Optional[logging.Handler] = None


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(_NAME if not name else f"{_NAME}.{name}")


def setup(verbose: int = 0) -> None:
    """按 verbose 计数配 stderr 日志。0=WARNING,1=INFO,>=2=DEBUG。幂等。

    注意:设 propagate=False 避免经 root 双打;因此**测试勿依赖 caplog 传播**——
    埋点测试不要调 setup(),改用 caplog.at_level(level, logger="asrkit")。
    """
    global _HANDLER
    level = logging.DEBUG if verbose >= 2 else logging.INFO if verbose == 1 else logging.WARNING
    logger = logging.getLogger(_NAME)
    logger.setLevel(level)
    if _HANDLER is None:                          # 幂等:只加一次 stderr handler
        _HANDLER = logging.StreamHandler(sys.stderr)
        _HANDLER.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(_HANDLER)
        logger.propagate = False
```

### 3.2 CLI `-v`(`cli.py`)

- 加 helper `_add_verbose(sp)`:`sp.add_argument("-v", "--verbose", action="count", default=0, help="verbose logging (-v INFO, -vv DEBUG)")`。
- 应用到受益子命令:`transcribe`、`run`、`stream`、`serve`(其余命令不需要)。
- `main()` 解析后、分发前:`from . import log; log.setup(getattr(a, "verbose", 0))`(非这些子命令时 `getattr` 得 0 → WARNING 静默,无副作用)。

### 3.3 `_http.py` 重试埋点(INFO)

在 `post()` 重试循环的两个重试点,`_sleep` 前打 INFO。加模块级 `from . import log`(或惰性 `log.get_logger("http")`):

```python
_LOG = log.get_logger("http")
...
# 异常重试点(idempotent 且 attempt<n):
delay = _backoff(attempt)
_LOG.info("retry %d/%d after %.1fs: %s (%s)", attempt + 1, n, delay, url, type(e).__name__)
_sleep(delay)
# 状态码重试点(status in codes 且 attempt<n):
delay = _retry_after(resp) or _backoff(attempt)
_LOG.info("retry %d/%d after %.1fs: %s (HTTP %d)", attempt + 1, n, delay, url, resp.status_code)
_sleep(delay)
```

(把原先直接 `_sleep(_backoff(attempt))` / `_sleep(_retry_after(resp) or _backoff(attempt))` 改为先算 `delay`、打日志、再 `_sleep(delay)`——行为不变,只加可见性。)

### 3.4 serve 埋点(INFO)(`server.py`)

- 模块级 `_LOG = log.get_logger("serve")`。
- `transcriptions` 端点:成功/失败各打一行 INFO(model、字节数、response_format、latency、状态);错误从 raw `print(...)` 改 `_LOG.exception("transcription error: %s", model)`(保留 500 响应体不变)。
- serve 的 verbose 由 cli `serve` 分支 `log.setup(a.verbose)` 点亮(logger 进程级,serve() 无需传参)。

### 3.5 CLI 转写 metrics(DEBUG)(`cli.py`)

单文件转写路径拿到 `result` 后:`log.get_logger().debug("model=%s metrics=%s", a.model, result.metrics)`(仅 `-vv` 时出)。

## 4. 契约/行为影响

- 纯增量 + 向后兼容:默认(无 `-v`)WARNING → **看不到任何新输出**,现有 stdout/stderr 契约不变。
- 无新依赖;作为库 import 零副作用(NullHandler + 不 setup 就不打)。

## 5. 改动清单

| 文件 | 改动 |
|---|---|
| `src/asrkit/log.py` | **新增**:`get_logger` / `setup` / NullHandler |
| `src/asrkit/cli.py` | `_add_verbose` + 应用到 transcribe/run/stream/serve;`main()` 调 `log.setup`;转写 DEBUG metrics |
| `src/asrkit/_http.py` | 两个重试点加 INFO 日志(行为不变) |
| `src/asrkit/server.py` | 请求 INFO + 错误改 `_LOG.exception` |
| `tests/test_logging.py` | **新增** |
| `docs/usage.md` / `CHANGELOG.md` | `-v` 用法 + `[Unreleased]` |

## 6. 测试

- **setup 等级**:`log.setup(0/1/2)` 后 `logging.getLogger("asrkit").level` == WARNING/INFO/DEBUG。
- **setup 幂等**:连调两次,`asrkit` logger 上非 NullHandler 的 StreamHandler 只 1 个(handler 数不翻倍)。
- **库安全**:未 setup 时 `logging.getLogger("asrkit")` 含 `NullHandler`;`get_logger("x")` 返回 `asrkit.x` 子 logger。
- **_http 重试打 INFO**(不调 setup,用 `caplog.at_level(logging.INFO, logger="asrkit")`):复用 test_http 的 mock 触发一次重试(429 或异常),断言 caplog 里有 `retry` 且含 URL/原因;计费幂等语义不变(沿用现有 test_http 断言不回归)。
- **serve 错误走 logger**(caplog):触发端点异常,断言 asrkit logger 有 error 记录(若 TestClient 装配复杂,退而测 `server._LOG` 存在 + 成功路径 INFO;实现者按可行性选,报告说明)。
- **CLI `-v` 点亮**:`cli.main(["--help"])` 不受影响;带 `-v` 的子命令解析出 `verbose>=1`(可测 `_add_verbose` 挂上了参数)。
- **回归**:现有 http/serve/全量测试仍绿;默认无 `-v` 时无新增 stderr 噪音。

## 7. 不做(YAGNI)

JSON 结构化日志、日志落文件/轮转、`ASRKIT_LOG_LEVEL` env(先靠 flag,需要再加)、把面向用户的 `[error]`/`[warn]` print 改成 logger。

## 8. 风险

- `propagate=False` 是刻意的(防 root 双打),代价是 caplog 需 `at_level(logger="asrkit")` 且测试不调 setup —— 已在 §6 规避。
- `_http` 改动仅"先算 delay 再 sleep",逻辑等价,重试/计费语义零变化。
