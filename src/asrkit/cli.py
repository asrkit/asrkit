"""asrkit command-line interface."""
from __future__ import annotations

from typing import Optional

from . import api as api  # noqa: F401 - re-exported for tests and external monkeypatches


def main(argv: Optional[list] = None) -> int:
    from . import log
    from .cli_commands import config, diagnostics, engines, models, stream, transcribe
    from .cli_commands.parser import build_parser

    p = build_parser()
    a = p.parse_args(argv)
    a._api = api
    log.setup(getattr(a, "verbose", 0))

    handlers = {
        "list": models.handle,
        "completion": models.handle,
        "search": models.handle,
        "show": models.handle,
        "pull": models.handle,
        "rm": models.handle,
        "add-model": models.handle,
        "engine": engines.handle,
        "config": config.handle,
        "doctor": diagnostics.handle,
        "serve": diagnostics.handle,
        "run": transcribe.handle,
        "transcribe": transcribe.handle,
        "stream": stream.handle,
    }
    cmd = getattr(a, "cmd", None)
    if not isinstance(cmd, str):
        p.print_help()
        return 0
    handler = handlers.get(cmd)
    if handler is None:
        p.print_help()
        return 0
    return handler(a)


if __name__ == "__main__":
    raise SystemExit(main())
