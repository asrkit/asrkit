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
