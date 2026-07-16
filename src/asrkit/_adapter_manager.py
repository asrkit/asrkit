"""`serve` 进程内的 adapter 缓存、并发与生命周期管理。

这是 HTTP runtime 的内部边界，不是公开 Python API。所有阻塞方法均应由调用方
放入 worker thread，避免构造模型或等待串行锁阻塞 event loop。
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional


class _AdapterManagerClosed(RuntimeError):
    """manager 已进入 shutdown，不再接受新 lease。"""


@dataclass
class _Slot:
    model: str
    users: int = 0
    building: bool = True
    adapter: Any = None
    error: Optional[BaseException] = None
    concurrent: bool = False
    detached: bool = False
    close_started: bool = False
    close_finished: bool = False
    ready: threading.Event = field(default_factory=threading.Event)
    invocation_lock: threading.Lock = field(default_factory=threading.Lock)


def _supports_concurrent_calls(adapter: Any) -> bool:
    """用 duck typing 兼容新旧和第三方 adapter。

    缺少 hook 时保守地串行；也允许第三方过渡期用 bool 属性。
    """
    hook = getattr(adapter, "supports_concurrent_calls", None)
    if hook is None:
        return False
    return bool(hook() if callable(hook) else hook)


def _close_adapter(adapter: Any) -> None:
    close = getattr(adapter, "close", None)
    if callable(close):
        close()


class _AdapterLease:
    """对一个已缓存 adapter slot 的幂等使用权。"""

    def __init__(self, manager: "_AdapterManager", slot: _Slot):
        self._manager = manager
        self._slot = slot
        self._release_lock = threading.Lock()
        self._released = False

    @property
    def adapter(self) -> Any:
        return self._slot.adapter

    def _ensure_active(self) -> None:
        with self._release_lock:
            if self._released:
                raise RuntimeError("adapter lease has already been released")

    def invoke(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """调用一次 adapter 方法；非共享 adapter 的锁覆盖整次调用。"""
        self._ensure_active()
        context = nullcontext() if self._slot.concurrent else self._slot.invocation_lock
        with context:
            return getattr(self._slot.adapter, method)(*args, **kwargs)

    def iterate(self, method: str, *args: Any, **kwargs: Any) -> Iterator[Any]:
        """返回一个在整个迭代期间持有串行锁的生成器。"""
        self._ensure_active()

        def _iterator() -> Iterator[Any]:
            context = nullcontext() if self._slot.concurrent else self._slot.invocation_lock
            with context:
                source = iter(getattr(self._slot.adapter, method)(*args, **kwargs))
                try:
                    yield from source
                finally:
                    close = getattr(source, "close", None)
                    if callable(close):
                        close()

        return _iterator()

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._manager._release(self._slot)

    def discard(self) -> None:
        """释放并从缓存摘除 slot，用于配置失效等可恢复构造状态。"""
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._manager._release(self._slot, discard=True)

    def __enter__(self) -> "_AdapterLease":
        self._ensure_active()
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.release()


class _AdapterManager:
    """app-scoped adapter LRU；single-flight 构造，活跃 slot 不淘汰。"""

    def __init__(self, factory: Callable[[str], Any], *, capacity: int = 8):
        if capacity <= 0:
            raise ValueError("adapter cache capacity must be positive")
        self._factory = factory
        self._capacity = capacity
        self._condition = threading.Condition(threading.RLock())
        self._cache: "OrderedDict[str, _Slot]" = OrderedDict()
        self._all_slots: list[_Slot] = []
        self._closed = False

    @property
    def cache_size(self) -> int:
        with self._condition:
            return len(self._cache)

    def lease(self, model: str) -> _AdapterLease:
        """取得 model 的 lease。本方法可阻塞，必须在 worker thread 调用。"""
        with self._condition:
            if self._closed:
                raise _AdapterManagerClosed("adapter manager is shutting down")
            slot = self._cache.get(model)
            builder = slot is None
            if slot is None:
                slot = _Slot(model=model)
                self._cache[model] = slot
                self._all_slots.append(slot)
            else:
                self._cache.move_to_end(model)
            # 在等待构造前即预留 user，shutdown 不会提前 close。
            slot.users += 1

        if builder:
            self._build(slot)
        else:
            slot.ready.wait()

        with self._condition:
            if slot.error is not None:
                error = slot.error
                self._drop_failed_reservation_locked(slot)
                raise error
            if slot.adapter is None:  # pragma: no cover - 内部不变式防线
                self._drop_failed_reservation_locked(slot)
                raise RuntimeError("adapter construction completed without an adapter")
            return _AdapterLease(self, slot)

    # 过渡别名，便于内部调用者表达“取得”语义。
    acquire = lease

    def _build(self, slot: _Slot) -> None:
        adapter = None
        try:
            adapter = self._factory(slot.model)
            concurrent = _supports_concurrent_calls(adapter)
        except BaseException as error:
            if adapter is not None:
                try:
                    _close_adapter(adapter)
                except Exception:
                    pass
            with self._condition:
                slot.error = error
                slot.building = False
                if self._cache.get(slot.model) is slot:
                    del self._cache[slot.model]
                slot.ready.set()
                self._condition.notify_all()
            return

        with self._condition:
            slot.adapter = adapter
            slot.concurrent = concurrent
            slot.building = False
            slot.ready.set()
            self._condition.notify_all()

    def _drop_failed_reservation_locked(self, slot: _Slot) -> None:
        slot.users -= 1
        if slot.users == 0 and slot in self._all_slots:
            slot.close_finished = True
            self._all_slots.remove(slot)
        self._condition.notify_all()

    def _claim_close_locked(self, slot: _Slot) -> bool:
        if (slot.adapter is None or slot.users != 0 or slot.close_started
                or slot.building):
            return False
        slot.close_started = True
        return True

    def _detach_locked(self, slot: _Slot) -> None:
        slot.detached = True
        if self._cache.get(slot.model) is slot:
            del self._cache[slot.model]

    def _trim_locked(self) -> list[_Slot]:
        claimed: list[_Slot] = []
        while len(self._cache) > self._capacity:
            victim = next((candidate for candidate in self._cache.values()
                           if not candidate.building and candidate.users == 0), None)
            if victim is None:
                break
            self._detach_locked(victim)
            if self._claim_close_locked(victim):
                claimed.append(victim)
        return claimed

    def _finish_close(self, slot: _Slot) -> None:
        try:
            _close_adapter(slot.adapter)
        except Exception:
            # close 是最佳努力资源回收；不能因第三方 hook 异常破坏 manager。
            pass
        finally:
            with self._condition:
                slot.close_finished = True
                if slot in self._all_slots:
                    self._all_slots.remove(slot)
                self._condition.notify_all()

    def _release(self, slot: _Slot, *, discard: bool = False) -> None:
        claimed: list[_Slot] = []
        with self._condition:
            if slot.users <= 0:  # pragma: no cover - lease.release 自身已幂等
                return
            slot.users -= 1
            if discard:
                self._detach_locked(slot)
            if slot.users == 0 and (slot.detached or self._closed):
                self._detach_locked(slot)
                if self._claim_close_locked(slot):
                    claimed.append(slot)
            claimed.extend(self._trim_locked())
            self._condition.notify_all()

        for candidate in claimed:
            self._finish_close(candidate)

    def shutdown(self, timeout: Optional[float] = 1.0) -> bool:
        """停止新 lease，有界等待活跃 lease，超时后由 release 延迟 close。"""
        if timeout is not None and timeout < 0:
            raise ValueError("shutdown timeout must be non-negative or None")

        claimed: list[_Slot] = []
        with self._condition:
            self._closed = True
            for slot in list(self._cache.values()):
                self._detach_locked(slot)
                if self._claim_close_locked(slot):
                    claimed.append(slot)

        # shutdown 的 close hook 未必可控，放入 daemon thread 才能保证超时边界。
        for slot in claimed:
            threading.Thread(
                target=self._finish_close,
                args=(slot,),
                name=f"asrkit-close-{slot.model}",
                daemon=True,
            ).start()

        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._all_slots:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True
