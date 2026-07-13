"""Streaming CLI command."""
from __future__ import annotations

import sys

from .shared import add_verbose, cfg, opts


def add_parsers(sub) -> None:
    stp = sub.add_parser("stream", help="stream-transcribe one file with a streaming model")
    stp.add_argument("model")
    stp.add_argument("audio", nargs="?", default=None)
    stp.add_argument("--mic", action="store_true", help="read live audio from the microphone (needs asrkit[mic])")
    stp.add_argument("--device", default=None, help="microphone device index or name substring (with --mic)")
    stp.add_argument("--model-dir", default=None)
    stp.add_argument("--language", default=None,
                     help="language hint (e.g. zh, en) — helps Whisper-family models")
    stp.add_argument("--convert", action="store_true",
                     help="decode/resample/downmix to fit the local engine "
                          "(off by default: on mismatch it errors)")
    add_verbose(stp)


def handle(a) -> int:
    from .. import emit, registry
    from ..audio import AudioFormatError

    run_cfg, run_opts = cfg(a), opts(a)
    live = sys.stderr.isatty()
    if a.mic and a.audio:                     # v2:诚实报错,不静默忽略
        print("[error] cannot combine --mic with an audio file", file=sys.stderr)
        return emit.EXIT_USAGE
    if a.device and not a.mic:
        print("[error] --device only applies with --mic", file=sys.stderr)
        return emit.EXIT_USAGE
    try:
        if a.mic:
            dev = a.device
            if isinstance(dev, str) and dev.isdigit():
                dev = int(dev)
            stream = a._api.transcribe_stream_mic(
                a.model, config=run_cfg, opts=run_opts, device=dev)
        else:
            if not a.audio:
                print("[error] stream needs an audio file, or --mic", file=sys.stderr)
                return emit.EXIT_USAGE
            stream = a._api.transcribe_stream(
                a.model, a.audio, config=run_cfg, opts=run_opts)
    except registry.ModelNotFoundError as e:
        print(f"[error] {e}", file=sys.stderr)
        return emit.EXIT_MODEL_NOT_FOUND
    except ValueError as e:
        print(f"[error] {e}", file=sys.stderr)
        return emit.EXIT_USAGE
    except RuntimeError as e:                 # mic 缺 sounddevice
        print(f"[error] {e}", file=sys.stderr)
        return emit.EXIT_ERROR
    last_text = ""
    try:
        for pr in stream:
            if pr.error:
                if live:
                    sys.stderr.write("\r\x1b[K")
                    sys.stderr.flush()
                print(f"[error] {pr.error}", file=sys.stderr)
                return emit.EXIT_FAILED
            if pr.is_final:
                if live:
                    sys.stderr.write("\r\x1b[K")
                    sys.stderr.flush()
                print(pr.text)
                last_text = pr.text
            else:
                last_text = pr.text
                if live:
                    sys.stderr.write("\r\x1b[K" + pr.text)
                    sys.stderr.flush()
    except AudioFormatError as e:
        if live:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()
        print(f"[error] {e}", file=sys.stderr)
        return emit.EXIT_FAILED
    except KeyboardInterrupt:                 # mic Ctrl-C 兜底(若未在 record_chunks 内被吞)
        if live:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()
        if last_text:
            print(last_text)
        return emit.EXIT_OK
    return emit.EXIT_OK
