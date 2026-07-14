"""asrkit-cloud 命令入口。"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from .security import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_UPLOAD_MB,
    DEFAULT_REQUEST_TIMEOUT_S,
    DEFAULT_SHUTDOWN_TIMEOUT_S,
    SecurityError,
)
from .settings import activate_environment, resolve_settings


def build_parser() -> argparse.ArgumentParser:
    from .. import __version__

    parser = argparse.ArgumentParser(
        prog="asrkit-cloud",
        description="Run ASRKit's standalone cloud transcription service.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"asrkit-cloud {__version__}")
    parser.add_argument("--embedded", action="store_true",
                        help="enable machine-readable lifecycle and hardened local defaults")
    parser.add_argument("--host", default="127.0.0.1",
                        help="loopback bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int,
                        help="bind port (default: 11435, or 0 in embedded mode)")
    parser.add_argument("--parent-pid", type=int,
                        help="host process id to monitor (required in embedded mode)")
    parser.add_argument("--data-dir",
                        help="writable private data directory (required in embedded mode)")
    parser.add_argument("--max-upload-mb", type=int, default=DEFAULT_MAX_UPLOAD_MB,
                        help=f"maximum audio upload size (default: {DEFAULT_MAX_UPLOAD_MB} MiB)")
    parser.add_argument("--max-concurrency", type=int, default=DEFAULT_MAX_CONCURRENCY,
                        help=f"maximum active transcriptions (default: {DEFAULT_MAX_CONCURRENCY})")
    parser.add_argument("--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT_S,
                        help=f"transcription timeout in seconds (default: {DEFAULT_REQUEST_TIMEOUT_S:g})")
    parser.add_argument("--shutdown-timeout", type=int, default=DEFAULT_SHUTDOWN_TIMEOUT_S,
                        help=f"graceful shutdown timeout in seconds (default: {DEFAULT_SHUTDOWN_TIMEOUT_S:g})")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="verbose logging to stderr (-v INFO, -vv DEBUG)")
    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = resolve_settings(
            embedded=args.embedded,
            host=args.host,
            port=args.port,
            parent_pid=args.parent_pid,
            data_dir=args.data_dir,
            token=os.environ.get("ASRKIT_GATEWAY_TOKEN"),
            max_upload_mb=args.max_upload_mb,
            max_concurrency=args.max_concurrency,
            request_timeout_s=args.request_timeout,
            shutdown_timeout_s=args.shutdown_timeout,
        )
    except SecurityError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    from .. import __version__, log, registry

    try:
        registry.configure_profile("cloud")
    except (RuntimeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    activate_environment(settings)
    log.setup(args.verbose)

    try:
        if settings.embedded:
            from .lifecycle import run_embedded
            return run_embedded(settings, __version__)

        from .. import server
        print(
            f"asrkit-cloud serving on http://{settings.host}:{settings.port}  "
            "(cloud-only, OpenAI-compatible /v1)",
            file=sys.stderr,
        )
        server.serve(
            host=settings.host,
            port=settings.port,
            shutdown_timeout_s=settings.shutdown_timeout_s,
            **settings.server_options(__version__),
        )
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 0
