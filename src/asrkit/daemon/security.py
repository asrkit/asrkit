"""asrkit-cloud 的本机绑定、token 与数据目录安全约束。"""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import Optional

DEFAULT_MAX_UPLOAD_MB = 200
DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_REQUEST_TIMEOUT_S = 300.0
DEFAULT_SHUTDOWN_TIMEOUT_S = 10
MIN_TOKEN_LENGTH = 32


class SecurityError(ValueError):
    """不满足 asrkit-cloud 安全约束的配置。"""


def require_loopback(host: str) -> None:
    if host not in ("127.0.0.1", "::1"):
        raise SecurityError("asrkit-cloud only binds to 127.0.0.1 or ::1")


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
    probe_fd: Optional[int] = None
    probe_path: Optional[str] = None
    try:
        for item in (root, tmp, logs):
            if item != root and item.is_symlink():
                raise SecurityError(f"daemon directory must not be a symlink: {item}")
            existed = item.exists()
            item.mkdir(parents=item == root, exist_ok=True, mode=0o700)
            item_mode = item.lstat().st_mode
            if stat.S_ISLNK(item_mode):
                raise SecurityError(f"daemon directory must not be a symlink: {item}")
            if not stat.S_ISDIR(item_mode):
                raise SecurityError(f"daemon path must be a directory: {item}")
            if not existed:
                try:
                    os.chmod(item, 0o700)
                except OSError:
                    pass
                item_mode = item.lstat().st_mode
            if os.name != "nt" and stat.S_IMODE(item_mode) & 0o077:
                raise SecurityError(f"daemon directory must be private (0700): {item}")
        probe_fd, probe_path = tempfile.mkstemp(
            prefix=".asrkit-write-probe-",
            dir=root,
        )
        os.write(probe_fd, b"\0")
        os.close(probe_fd)
        probe_fd = None
        os.unlink(probe_path)
        probe_path = None
    except SecurityError:
        raise
    except OSError as exc:
        raise SecurityError(f"data directory is not writable: {root}") from exc
    finally:
        if probe_fd is not None:
            try:
                os.close(probe_fd)
            except OSError:
                pass
        if probe_path is not None:
            try:
                os.unlink(probe_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
    return str(root), str(tmp)
