"""Cloud-only ASRKit daemon command-line entry point."""
from __future__ import annotations

import argparse
import sys
from typing import Optional


def build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="asrkitd",
        description="Run ASRKit's standalone cloud transcription service.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"asrkitd {__version__}")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind host (default: 127.0.0.1, local only)")
    parser.add_argument("--port", type=int, default=11435, help="port (default: 11435)")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="verbose logging to stderr (-v INFO, -vv DEBUG)")
    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from . import log, registry

    try:
        registry.configure_profile("cloud")
    except (RuntimeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    from . import server

    log.setup(args.verbose)
    if args.host not in ("127.0.0.1", "localhost"):
        print(f"[warn] binding to {args.host} exposes the server to the network", file=sys.stderr)
    print(
        f"asrkitd serving on http://{args.host}:{args.port}  "
        "(cloud-only, OpenAI-compatible /v1)",
        file=sys.stderr,
    )
    try:
        server.serve(host=args.host, port=args.port)
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
