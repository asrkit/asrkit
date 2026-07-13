"""asrkitd embedded 启动握手、父进程监控与优雅退出。"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import threading
from collections.abc import Generator
from types import FrameType
from typing import Any, Optional

from .settings import DaemonSettings


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _emit_control(event: dict) -> None:
    print(json.dumps(event, separators=(",", ":")), file=sys.stdout, flush=True)


def _base_url(host: str, port: int) -> str:
    rendered_host = f"[{host}]" if ":" in host else host
    return f"http://{rendered_host}:{port}/v1"


def _bound_port(uvicorn_server) -> int:
    for listener in getattr(uvicorn_server, "servers", ()):
        for sock in getattr(listener, "sockets", ()) or ():
            return int(sock.getsockname()[1])
    raise RuntimeError("asrkitd started without a bound socket")


async def monitor_parent(parent_pid: int, uvicorn_server, interval_s: float = 1.0) -> str:
    while not uvicorn_server.should_exit:
        if not pid_exists(parent_pid):
            uvicorn_server.should_exit = True
            return "parent_exited"
        await asyncio.sleep(interval_s)
    return "server_stopped"


def _embedded_server_type(uvicorn: Any) -> type[Any]:
    from uvicorn.server import HANDLED_SIGNALS

    class EmbeddedServer(uvicorn.Server):
        shutdown_reason: Optional[str] = None

        def handle_exit(self, sig: int, frame: Optional[FrameType]) -> None:
            self.shutdown_reason = "signal"
            super().handle_exit(sig, frame)

        @contextlib.contextmanager
        def capture_signals(self) -> Generator[None, None, None]:
            if threading.current_thread() is not threading.main_thread():
                yield
                return
            original_handlers = {
                sig: signal.signal(sig, self.handle_exit) for sig in HANDLED_SIGNALS
            }
            try:
                yield
            finally:
                for sig, handler in original_handlers.items():
                    signal.signal(sig, handler)

    return EmbeddedServer


async def _serve_embedded(settings: DaemonSettings, version: str) -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError('asrkitd needs serve dependencies; install "asrkit[serve]"') from exc

    from .. import server

    if settings.parent_pid is None or not pid_exists(settings.parent_pid):
        raise RuntimeError("parent process is not running")

    app = server.build_app(**settings.server_options(version))
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        access_log=False,
        timeout_graceful_shutdown=settings.shutdown_timeout_s,
    )
    daemon = _embedded_server_type(uvicorn)(config)
    server_task = asyncio.create_task(daemon.serve())
    monitor_task: Optional[asyncio.Task] = None
    ready = False
    reason = "server_stopped"
    try:
        while not daemon.started:
            if server_task.done():
                error = server_task.exception()
                if error:
                    raise RuntimeError("asrkitd failed before becoming ready") from error
                raise RuntimeError("asrkitd stopped before becoming ready")
            await asyncio.sleep(0.01)

        port = _bound_port(daemon)
        _emit_control({
            "event": "ready",
            "base_url": _base_url(settings.host, port),
            "pid": os.getpid(),
            "protocol_version": settings.protocol_version,
        })
        ready = True
        monitor_task = asyncio.create_task(monitor_parent(settings.parent_pid, daemon))
        await server_task
        if daemon.shutdown_reason is not None:
            reason = daemon.shutdown_reason
        elif monitor_task.done() and not monitor_task.cancelled():
            reason = monitor_task.result()
    finally:
        if monitor_task is not None and not monitor_task.done():
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        if not server_task.done():
            daemon.should_exit = True
            await server_task
        if ready:
            _emit_control({"event": "shutdown", "reason": reason})
    return 0


def run_embedded(settings: DaemonSettings, version: str) -> int:
    return asyncio.run(_serve_embedded(settings, version))
