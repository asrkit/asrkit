"""Tests for asrkit logging / --verbose (P3)."""
import logging

import pytest

from asrkit import log


@pytest.fixture(autouse=True)
def _isolate_logging():
    """每用例前后复位 asrkit logger,防 propagate=False 泄漏。"""
    log._reset()
    yield
    log._reset()


def test_setup_levels():
    for v, want in [(0, logging.WARNING), (1, logging.INFO), (2, logging.DEBUG)]:
        log._reset()
        log.setup(v)
        assert logging.getLogger("asrkit").level == want


def test_setup_idempotent_no_duplicate_handlers():
    log.setup(1)
    log.setup(2)
    stream_handlers = [h for h in logging.getLogger("asrkit").handlers
                       if isinstance(h, logging.StreamHandler)
                       and not isinstance(h, logging.NullHandler)]
    assert len(stream_handlers) == 1
    assert logging.getLogger("asrkit").level == logging.DEBUG   # 二次 setup 更新等级


def test_library_safe_nullhandler():
    # 未 setup:asrkit logger 应有 NullHandler,import 不刷屏
    handlers = logging.getLogger("asrkit").handlers
    assert any(isinstance(h, logging.NullHandler) for h in handlers)


def test_get_logger_child():
    assert log.get_logger("http").name == "asrkit.http"
    assert log.get_logger().name == "asrkit"


def test_ensure_configured_installs_then_no_downgrade():
    log.setup(2)                              # DEBUG
    log.ensure_configured()                   # 不应降级
    assert logging.getLogger("asrkit").level == logging.DEBUG
    log._reset()
    log.ensure_configured()                   # 未配置 → 装 WARNING handler
    stream_handlers = [h for h in logging.getLogger("asrkit").handlers
                       if isinstance(h, logging.StreamHandler)
                       and not isinstance(h, logging.NullHandler)]
    assert len(stream_handlers) == 1


def test_http_retry_logs_info(monkeypatch, caplog):
    """_http 重试打 INFO(不调 setup,用 caplog.at_level)。"""
    from asrkit import _http

    class _Resp:
        def __init__(self, code):
            self.status_code = code
            self.headers = {}
            self.text = ""

        def json(self):
            return {}
    calls = {"n": 0}
    def fake_post(url, **kw):
        calls["n"] += 1
        return _Resp(429 if calls["n"] == 1 else 200)   # 首次 429 触发一次重试
    # session().post → fake
    monkeypatch.setattr(_http, "_session", lambda: type("S", (), {"post": staticmethod(fake_post)})())
    monkeypatch.setattr(_http, "_sleep", lambda *_: None)
    with caplog.at_level(logging.INFO, logger="asrkit"):
        r = _http.post("http://x/submit", idempotent=True, retries=2)
    assert r.status_code == 200
    assert any("retry" in rec.message for rec in caplog.records)
