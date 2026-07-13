"""asrkitd 的本机绑定、token 与数据目录安全约束。"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional

DEFAULT_MAX_UPLOAD_MB = 200
DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_REQUEST_TIMEOUT_S = 300.0
DEFAULT_SHUTDOWN_TIMEOUT_S = 10
MIN_TOKEN_LENGTH = 32


class SecurityError(ValueError):
    """不满足 asrkitd 安全约束的配置。"""


def require_loopback(host: str) -> None:
    if host not in ("127.0.0.1", "::1"):
        raise SecurityError("asrkitd only binds to 127.0.0.1 or ::1")


def validate_token(token: Optional[str], *, required: bool) -> Optional[str]:
    if not token:
        if required:
            raise SecurityError(
                "embedded mode needs ASRKIT_GATEWAY_TOKEN with at least 32 characters")
        return None
    if len(token) < MIN_TOKEN_LENGTH:
        raise SecurityError("ASRKIT_GATEWAY_TOKEN must contain at least 32 characters")
    return token


def prepare_data_dir(path: str) -> tuple[str, str]:
    root = Path(path).expanduser().resolve()
    tmp = root / "tmp"
    logs = root / "logs"
    try:
        for item in (root, tmp, logs):
            existed = item.exists()
            item.mkdir(parents=item == root, exist_ok=True, mode=0o700)
            if not existed:
                try:
                    os.chmod(item, 0o700)
                except OSError:
                    pass
            if os.name != "nt" and stat.S_IMODE(item.stat().st_mode) & 0o077:
                raise SecurityError(f"daemon directory must be private (0700): {item}")
        probe = root / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()
    except SecurityError:
        raise
    except OSError as exc:
        raise SecurityError(f"data directory is not writable: {root}") from exc
    return str(root), str(tmp)
