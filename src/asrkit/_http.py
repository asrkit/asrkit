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

from . import log

_LOG = log.get_logger("http")

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
            delay = _backoff(attempt)
            _LOG.info("retry %d/%d after %.1fs: %s (ConnectTimeout)", attempt + 1, n, delay, url)
            _sleep(delay)
            continue
        except (ReadTimeout, _ConnectionError, Timeout) as e:  # 可能已发出/已处理 → 仅只读重
            if idempotent and attempt < n:
                delay = _backoff(attempt)
                _LOG.info("retry %d/%d after %.1fs: %s (%s)", attempt + 1, n, delay, url, type(e).__name__)
                _sleep(delay)
                continue
            raise
        if resp.status_code in codes and attempt < n:
            delay = _retry_after(resp) or _backoff(attempt)
            _LOG.info("retry %d/%d after %.1fs: %s (HTTP %d)", attempt + 1, n, delay, url, resp.status_code)
            _sleep(delay)
            continue
        return resp
    raise AssertionError("unreachable")  # 循环必在 return/raise 收尾
