"""HTTP adapter 管理器的并发、LRU 与生命周期契约。"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from asrkit._adapter_manager import _AdapterManager, _AdapterManagerClosed


class _Adapter:
    def __init__(self, *, concurrent=False):
        self.concurrent = concurrent
        self.close_calls = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def supports_concurrent_calls(self):
        return self.concurrent

    def close(self):
        self.close_calls += 1

    def call(self, entered=None, release=None):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        if entered is not None:
            entered.set()
        if release is not None:
            assert release.wait(2)
        else:
            time.sleep(0.02)
        with self.lock:
            self.active -= 1
        return "ok"

    def stream(self, entered, release):
        entered.set()
        yield "first"
        assert release.wait(2)
        yield "second"


def test_same_model_construction_is_single_flight():
    started = threading.Event()
    release = threading.Event()
    adapter = _Adapter()
    calls = 0
    calls_lock = threading.Lock()

    def factory(_model):
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(2)
        return adapter

    manager = _AdapterManager(factory, capacity=4)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(manager.lease, "same") for _ in range(8)]
        assert started.wait(2)
        release.set()
        leases = [future.result(timeout=2) for future in futures]

    assert calls == 1
    assert all(lease.adapter is adapter for lease in leases)
    for lease in leases:
        lease.release()
    assert manager.shutdown(timeout=1) is True
    assert adapter.close_calls == 1


def test_construction_failure_is_shared_but_next_call_retries():
    started = threading.Event()
    release = threading.Event()
    failure = RuntimeError("build failed")
    adapter = _Adapter()
    calls = 0

    def factory(_model):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            assert release.wait(2)
            raise failure
        return adapter

    manager = _AdapterManager(factory, capacity=2)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(manager.lease, "bad") for _ in range(4)]
        assert started.wait(2)
        # 等待者先进入同一个 in-flight slot，再让构造失败。
        time.sleep(0.03)
        release.set()
        errors = []
        for future in futures:
            with pytest.raises(RuntimeError) as caught:
                future.result(timeout=2)
            errors.append(caught.value)

    assert calls == 1
    assert all(error is failure for error in errors)
    lease = manager.lease("bad")
    assert calls == 2
    lease.release()
    manager.shutdown(timeout=1)


@pytest.mark.parametrize(("concurrent", "expected"), [(False, 1), (True, 2)])
def test_invocation_policy_is_duck_typed(concurrent, expected):
    adapter = _Adapter(concurrent=concurrent)
    manager = _AdapterManager(lambda _model: adapter, capacity=2)
    first = manager.lease("m")
    second = manager.lease("m")

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(first.invoke, "call")
        two = pool.submit(second.invoke, "call")
        assert one.result(timeout=2) == "ok"
        assert two.result(timeout=2) == "ok"

    assert adapter.max_active == expected
    first.release()
    second.release()
    manager.shutdown(timeout=1)


def test_stream_generator_holds_serialization_lock_until_exhausted():
    adapter = _Adapter()
    manager = _AdapterManager(lambda _model: adapter, capacity=2)
    stream_lease = manager.lease("m")
    call_lease = manager.lease("m")
    stream_entered = threading.Event()
    stream_release = threading.Event()
    call_entered = threading.Event()

    def consume():
        return list(stream_lease.iterate("stream", stream_entered, stream_release))

    with ThreadPoolExecutor(max_workers=2) as pool:
        stream_future = pool.submit(consume)
        assert stream_entered.wait(2)
        call_future = pool.submit(call_lease.invoke, "call", call_entered, None)
        assert not call_entered.wait(0.05)
        stream_release.set()
        assert stream_future.result(timeout=2) == ["first", "second"]
        assert call_future.result(timeout=2) == "ok"
        assert call_entered.is_set()

    stream_lease.release()
    call_lease.release()
    manager.shutdown(timeout=1)


def test_busy_slots_are_pinned_and_trimmed_after_release():
    adapters = {}

    def factory(model):
        adapters[model] = _Adapter()
        return adapters[model]

    manager = _AdapterManager(factory, capacity=1)
    first = manager.lease("A")
    second = manager.lease("B")
    assert manager.cache_size == 2
    assert adapters["A"].close_calls == adapters["B"].close_calls == 0

    second.release()
    assert manager.cache_size == 1
    assert adapters["B"].close_calls == 1
    assert adapters["A"].close_calls == 0

    first.release()
    manager.shutdown(timeout=1)
    assert adapters["A"].close_calls == 1
    assert adapters["B"].close_calls == 1


def test_shutdown_rejects_new_lease_and_defers_active_close_once():
    adapter = _Adapter()
    manager = _AdapterManager(lambda _model: adapter, capacity=1)
    lease = manager.lease("m")

    assert manager.shutdown(timeout=0) is False
    assert adapter.close_calls == 0
    with pytest.raises(_AdapterManagerClosed, match="shutting down"):
        manager.lease("new")

    lease.release()
    lease.release()
    assert adapter.close_calls == 1
    assert manager.shutdown(timeout=1) is True
    assert adapter.close_calls == 1


def test_lru_eviction_closes_adapter_exactly_once():
    adapters = {}

    def factory(model):
        adapters[model] = _Adapter()
        return adapters[model]

    manager = _AdapterManager(factory, capacity=1)
    manager.lease("A").release()
    manager.lease("B").release()
    assert adapters["A"].close_calls == 1
    assert adapters["B"].close_calls == 0

    manager.shutdown(timeout=1)
    manager.shutdown(timeout=1)
    assert adapters["A"].close_calls == 1
    assert adapters["B"].close_calls == 1


def test_discard_removes_recoverable_bad_instance_from_cache():
    adapters = []

    def factory(_model):
        adapter = _Adapter()
        adapters.append(adapter)
        return adapter

    manager = _AdapterManager(factory, capacity=2)
    bad = manager.lease("m")
    bad.discard()
    assert adapters[0].close_calls == 1

    good = manager.lease("m")
    assert good.adapter is not adapters[0]
    good.release()
    manager.shutdown(timeout=1)
    assert [adapter.close_calls for adapter in adapters] == [1, 1]
