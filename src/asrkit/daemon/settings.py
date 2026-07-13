"""asrkitd 参数归一与 embedded 配置验证。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from . import PROTOCOL_VERSION
from .security import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_UPLOAD_MB,
    DEFAULT_REQUEST_TIMEOUT_S,
    DEFAULT_SHUTDOWN_TIMEOUT_S,
    SecurityError,
    prepare_data_dir,
    require_loopback,
    validate_token,
)


@dataclass(frozen=True)
class DaemonSettings:
    embedded: bool
    host: str
    port: int
    parent_pid: Optional[int]
    data_dir: Optional[str]
    temp_dir: Optional[str]
    auth_token: Optional[str]
    max_upload_bytes: int
    max_concurrency: int
    request_timeout_s: float
    shutdown_timeout_s: int
    protocol_version: int = PROTOCOL_VERSION

    def server_options(self, version: str) -> dict:
        return {
            "auth_token": self.auth_token,
            "max_upload_bytes": self.max_upload_bytes,
            "max_concurrency": self.max_concurrency,
            "request_timeout_s": self.request_timeout_s,
            "temp_dir": self.temp_dir,
            "health_info": {
                "version": version,
                "protocol_version": self.protocol_version,
                "distribution": "cloud",
            },
        }


def resolve_settings(
    *,
    embedded: bool,
    host: str,
    port: Optional[int],
    parent_pid: Optional[int],
    data_dir: Optional[str],
    token: Optional[str],
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    shutdown_timeout_s: int = DEFAULT_SHUTDOWN_TIMEOUT_S,
) -> DaemonSettings:
    require_loopback(host)
    resolved_port = 0 if embedded and port is None else 11435 if port is None else port
    if not 0 <= resolved_port <= 65535:
        raise SecurityError("port must be between 0 and 65535")
    if not embedded and resolved_port == 0:
        raise SecurityError("port 0 requires --embedded so the selected port can be reported")
    if embedded and (parent_pid is None or parent_pid <= 0):
        raise SecurityError("embedded mode needs --parent-pid with a positive process id")
    if not embedded and parent_pid is not None:
        raise SecurityError("--parent-pid requires --embedded")
    if embedded and not data_dir:
        raise SecurityError("embedded mode needs --data-dir")
    if not 1 <= max_upload_mb <= 2048:
        raise SecurityError("--max-upload-mb must be between 1 and 2048")
    if not 1 <= max_concurrency <= 256:
        raise SecurityError("--max-concurrency must be between 1 and 256")
    if not 0 < request_timeout_s <= 3600:
        raise SecurityError("--request-timeout must be greater than 0 and at most 3600 seconds")
    if not 0 < shutdown_timeout_s <= 300:
        raise SecurityError("--shutdown-timeout must be greater than 0 and at most 300 seconds")

    auth_token = validate_token(token, required=embedded)
    root = tmp = None
    if data_dir:
        root, tmp = prepare_data_dir(data_dir)

    return DaemonSettings(
        embedded=embedded,
        host=host,
        port=resolved_port,
        parent_pid=parent_pid,
        data_dir=root,
        temp_dir=tmp,
        auth_token=auth_token,
        max_upload_bytes=max_upload_mb * 1024 * 1024,
        max_concurrency=max_concurrency,
        request_timeout_s=request_timeout_s,
        shutdown_timeout_s=shutdown_timeout_s,
    )


def activate_environment(settings: DaemonSettings) -> None:
    """让 embedded 模式不读取用户全局 ASRKit 配置。"""
    if settings.data_dir:
        os.environ["ASRKIT_CONFIG"] = os.path.join(settings.data_dir, "config.json")
