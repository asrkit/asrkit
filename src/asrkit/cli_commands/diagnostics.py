"""Doctor and serve CLI commands."""
from __future__ import annotations

import sys

from .shared import add_verbose


def add_parsers(sub) -> None:
    dp = sub.add_parser("doctor", help="diagnose install/config/engines/keys (add --net for reachability)")
    dp.add_argument("--net", action="store_true",
                    help="also check network reachability (download source / cloud)")

    svp = sub.add_parser("serve", help="run an OpenAI-compatible transcription server")
    svp.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1, local only)")
    svp.add_argument("--port", type=int, default=11435, help="port (default: 11435)")
    add_verbose(svp)


def handle(a) -> int:
    if a.cmd == "doctor":
        return _doctor(a)
    if a.cmd == "serve":
        return _serve(a)
    return 0


def _doctor(a) -> int:
    from .. import doctor

    marks = {"ok": "✓", "info": "○", "fail": "✗"}
    checks = doctor.diagnose(net=a.net)
    for chk in checks:
        print(f"{marks.get(chk.status, ' ')} {chk.name}: {chk.detail}")
    return 1 if any(chk.status == "fail" for chk in checks) else 0


def _serve(a) -> int:
    from .. import server

    if a.host not in ("127.0.0.1", "localhost"):
        print(f"[warn] binding to {a.host} exposes the server to the network", file=sys.stderr)
    print(f"asrkit serving on http://{a.host}:{a.port}  (OpenAI-compatible /v1)", file=sys.stderr)
    try:
        server.serve(host=a.host, port=a.port)
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    return 0
